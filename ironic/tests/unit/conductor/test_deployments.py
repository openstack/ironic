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

"""Tests for deployment aspects of the conductor."""

import mock
from oslo_config import cfg
from oslo_db import exception as db_exception
from oslo_utils import uuidutils

from ironic.common import exception
from ironic.common import states
from ironic.common import swift
from ironic.conductor import deployments
from ironic.conductor import steps as conductor_steps
from ironic.conductor import task_manager
from ironic.conductor import utils as conductor_utils
from ironic.db import api as dbapi
from ironic.drivers.modules import fake
from ironic.tests.unit.conductor import mgr_utils
from ironic.tests.unit.db import base as db_base
from ironic.tests.unit.objects import utils as obj_utils

CONF = cfg.CONF


@mgr_utils.mock_record_keepalive
class DoNodeDeployTestCase(mgr_utils.ServiceSetUpMixin, db_base.DbTestCase):
    @mock.patch('ironic.drivers.modules.fake.FakeDeploy.deploy')
    @mock.patch('ironic.drivers.modules.fake.FakeDeploy.prepare')
    def test__do_node_deploy_driver_raises_prepare_error(self, mock_prepare,
                                                         mock_deploy):
        self._start_service()
        # test when driver.deploy.prepare raises an ironic error
        mock_prepare.side_effect = exception.InstanceDeployFailure('test')
        node = obj_utils.create_test_node(self.context, driver='fake-hardware',
                                          provision_state=states.DEPLOYING,
                                          target_provision_state=states.ACTIVE)
        task = task_manager.TaskManager(self.context, node.uuid)

        self.assertRaises(exception.InstanceDeployFailure,
                          deployments.do_node_deploy, task,
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
    @mock.patch('ironic.drivers.modules.fake.FakeDeploy.prepare')
    def test__do_node_deploy_unexpected_prepare_error(self, mock_prepare,
                                                      mock_deploy):
        self._start_service()
        # test when driver.deploy.prepare raises an exception
        mock_prepare.side_effect = RuntimeError('test')
        node = obj_utils.create_test_node(self.context, driver='fake-hardware',
                                          provision_state=states.DEPLOYING,
                                          target_provision_state=states.ACTIVE)
        task = task_manager.TaskManager(self.context, node.uuid)

        self.assertRaises(RuntimeError,
                          deployments.do_node_deploy, task,
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
    def test__do_node_deploy_driver_raises_error_old(self, mock_deploy):
        # TODO(rloo): delete this after the deprecation period for supporting
        # non deploy_steps.
        # Mocking FakeDeploy.deploy before starting the service, causes
        # it not to be a deploy_step.
        self._start_service()
        # test when driver.deploy.deploy raises an ironic error
        mock_deploy.side_effect = exception.InstanceDeployFailure('test')
        node = obj_utils.create_test_node(self.context, driver='fake-hardware',
                                          provision_state=states.DEPLOYING,
                                          target_provision_state=states.ACTIVE)
        task = task_manager.TaskManager(self.context, node.uuid)

        self.assertRaises(exception.InstanceDeployFailure,
                          deployments.do_node_deploy, task,
                          self.service.conductor.id)
        node.refresh()
        self.assertEqual(states.DEPLOYFAIL, node.provision_state)
        # NOTE(deva): failing a deploy does not clear the target state
        #             any longer. Instead, it is cleared when the instance
        #             is deleted.
        self.assertEqual(states.ACTIVE, node.target_provision_state)
        self.assertIsNotNone(node.last_error)
        mock_deploy.assert_called_once_with(mock.ANY)

    @mock.patch('ironic.drivers.modules.fake.FakeDeploy.deploy')
    def test__do_node_deploy_driver_unexpected_exception_old(self,
                                                             mock_deploy):
        # TODO(rloo): delete this after the deprecation period for supporting
        # non deploy_steps.
        # Mocking FakeDeploy.deploy before starting the service, causes
        # it not to be a deploy_step.
        self._start_service()
        # test when driver.deploy.deploy raises an exception
        mock_deploy.side_effect = RuntimeError('test')
        node = obj_utils.create_test_node(self.context, driver='fake-hardware',
                                          provision_state=states.DEPLOYING,
                                          target_provision_state=states.ACTIVE)
        task = task_manager.TaskManager(self.context, node.uuid)

        self.assertRaises(RuntimeError,
                          deployments.do_node_deploy, task,
                          self.service.conductor.id)
        node.refresh()
        self.assertEqual(states.DEPLOYFAIL, node.provision_state)
        # NOTE(deva): failing a deploy does not clear the target state
        #             any longer. Instead, it is cleared when the instance
        #             is deleted.
        self.assertEqual(states.ACTIVE, node.target_provision_state)
        self.assertIsNotNone(node.last_error)
        mock_deploy.assert_called_once_with(mock.ANY)

    def _test__do_node_deploy_driver_exception(self, exc, unexpected=False):
        self._start_service()
        with mock.patch.object(fake.FakeDeploy,
                               'deploy', autospec=True) as mock_deploy:
            # test when driver.deploy.deploy() raises an exception
            mock_deploy.side_effect = exc
            node = obj_utils.create_test_node(
                self.context, driver='fake-hardware',
                provision_state=states.DEPLOYING,
                target_provision_state=states.ACTIVE)
            task = task_manager.TaskManager(self.context, node.uuid)

            deployments.do_node_deploy(task, self.service.conductor.id)
            node.refresh()
            self.assertEqual(states.DEPLOYFAIL, node.provision_state)
            # NOTE(deva): failing a deploy does not clear the target state
            #             any longer. Instead, it is cleared when the instance
            #             is deleted.
            self.assertEqual(states.ACTIVE, node.target_provision_state)
            self.assertIsNotNone(node.last_error)
            if unexpected:
                self.assertIn('Exception', node.last_error)
            else:
                self.assertNotIn('Exception', node.last_error)

            mock_deploy.assert_called_once_with(mock.ANY, task)

    def test__do_node_deploy_driver_ironic_exception(self):
        self._test__do_node_deploy_driver_exception(
            exception.InstanceDeployFailure('test'))

    def test__do_node_deploy_driver_unexpected_exception(self):
        self._test__do_node_deploy_driver_exception(RuntimeError('test'),
                                                    unexpected=True)

    @mock.patch.object(deployments, '_store_configdrive', autospec=True)
    @mock.patch('ironic.drivers.modules.fake.FakeDeploy.deploy')
    def test__do_node_deploy_ok_old(self, mock_deploy, mock_store):
        # TODO(rloo): delete this after the deprecation period for supporting
        # non deploy_steps.
        # Mocking FakeDeploy.deploy before starting the service, causes
        # it not to be a deploy_step.
        self._start_service()
        # test when driver.deploy.deploy returns DEPLOYDONE
        mock_deploy.return_value = states.DEPLOYDONE
        node = obj_utils.create_test_node(self.context, driver='fake-hardware',
                                          provision_state=states.DEPLOYING,
                                          target_provision_state=states.ACTIVE)
        task = task_manager.TaskManager(self.context, node.uuid)

        deployments.do_node_deploy(task, self.service.conductor.id)
        node.refresh()
        self.assertEqual(states.ACTIVE, node.provision_state)
        self.assertEqual(states.NOSTATE, node.target_provision_state)
        self.assertIsNone(node.last_error)
        mock_deploy.assert_called_once_with(mock.ANY)
        # assert _store_configdrive wasn't invoked
        self.assertFalse(mock_store.called)

    @mock.patch.object(deployments, '_store_configdrive', autospec=True)
    @mock.patch('ironic.drivers.modules.fake.FakeDeploy.deploy')
    def test__do_node_deploy_ok_configdrive_old(self, mock_deploy, mock_store):
        # TODO(rloo): delete this after the deprecation period for supporting
        # non deploy_steps.
        # Mocking FakeDeploy.deploy before starting the service, causes
        # it not to be a deploy_step.
        self._start_service()
        # test when driver.deploy.deploy returns DEPLOYDONE
        mock_deploy.return_value = states.DEPLOYDONE
        node = obj_utils.create_test_node(self.context, driver='fake-hardware',
                                          provision_state=states.DEPLOYING,
                                          target_provision_state=states.ACTIVE)
        task = task_manager.TaskManager(self.context, node.uuid)
        configdrive = 'foo'

        deployments.do_node_deploy(task, self.service.conductor.id,
                                   configdrive=configdrive)
        node.refresh()
        self.assertEqual(states.ACTIVE, node.provision_state)
        self.assertEqual(states.NOSTATE, node.target_provision_state)
        self.assertIsNone(node.last_error)
        mock_deploy.assert_called_once_with(mock.ANY)
        mock_store.assert_called_once_with(task.node, configdrive)

    @mock.patch.object(deployments, '_store_configdrive', autospec=True)
    def _test__do_node_deploy_ok(self, mock_store, configdrive=None,
                                 expected_configdrive=None):
        expected_configdrive = expected_configdrive or configdrive
        self._start_service()
        with mock.patch.object(fake.FakeDeploy,
                               'deploy', autospec=True) as mock_deploy:
            mock_deploy.return_value = None
            self.node = obj_utils.create_test_node(
                self.context, driver='fake-hardware', name=None,
                provision_state=states.DEPLOYING,
                target_provision_state=states.ACTIVE)
            task = task_manager.TaskManager(self.context, self.node.uuid)

            deployments.do_node_deploy(task, self.service.conductor.id,
                                       configdrive=configdrive)
            self.node.refresh()
            self.assertEqual(states.ACTIVE, self.node.provision_state)
            self.assertEqual(states.NOSTATE, self.node.target_provision_state)
            self.assertIsNone(self.node.last_error)
            mock_deploy.assert_called_once_with(mock.ANY, mock.ANY)
            if configdrive:
                mock_store.assert_called_once_with(task.node,
                                                   expected_configdrive)
            else:
                self.assertFalse(mock_store.called)

    def test__do_node_deploy_ok(self):
        self._test__do_node_deploy_ok()

    def test__do_node_deploy_ok_configdrive(self):
        configdrive = 'foo'
        self._test__do_node_deploy_ok(configdrive=configdrive)

    @mock.patch('openstack.baremetal.configdrive.build')
    def test__do_node_deploy_configdrive_as_dict(self, mock_cd):
        mock_cd.return_value = 'foo'
        configdrive = {'user_data': 'abcd'}
        self._test__do_node_deploy_ok(configdrive=configdrive,
                                      expected_configdrive='foo')
        mock_cd.assert_called_once_with({'uuid': self.node.uuid},
                                        network_data=None,
                                        user_data=b'abcd',
                                        vendor_data=None)

    @mock.patch('openstack.baremetal.configdrive.build')
    def test__do_node_deploy_configdrive_as_dict_with_meta_data(self, mock_cd):
        mock_cd.return_value = 'foo'
        configdrive = {'meta_data': {'uuid': uuidutils.generate_uuid(),
                                     'name': 'new-name',
                                     'hostname': 'example.com'}}
        self._test__do_node_deploy_ok(configdrive=configdrive,
                                      expected_configdrive='foo')
        mock_cd.assert_called_once_with(configdrive['meta_data'],
                                        network_data=None,
                                        user_data=None,
                                        vendor_data=None)

    @mock.patch('openstack.baremetal.configdrive.build')
    def test__do_node_deploy_configdrive_with_network_data(self, mock_cd):
        mock_cd.return_value = 'foo'
        configdrive = {'network_data': {'links': []}}
        self._test__do_node_deploy_ok(configdrive=configdrive,
                                      expected_configdrive='foo')
        mock_cd.assert_called_once_with({'uuid': self.node.uuid},
                                        network_data={'links': []},
                                        user_data=None,
                                        vendor_data=None)

    @mock.patch('openstack.baremetal.configdrive.build')
    def test__do_node_deploy_configdrive_and_user_data_as_dict(self, mock_cd):
        mock_cd.return_value = 'foo'
        configdrive = {'user_data': {'user': 'data'}}
        self._test__do_node_deploy_ok(configdrive=configdrive,
                                      expected_configdrive='foo')
        mock_cd.assert_called_once_with({'uuid': self.node.uuid},
                                        network_data=None,
                                        user_data=b'{"user": "data"}',
                                        vendor_data=None)

    @mock.patch('openstack.baremetal.configdrive.build')
    def test__do_node_deploy_configdrive_with_vendor_data(self, mock_cd):
        mock_cd.return_value = 'foo'
        configdrive = {'vendor_data': {'foo': 'bar'}}
        self._test__do_node_deploy_ok(configdrive=configdrive,
                                      expected_configdrive='foo')
        mock_cd.assert_called_once_with({'uuid': self.node.uuid},
                                        network_data=None,
                                        user_data=None,
                                        vendor_data={'foo': 'bar'})

    @mock.patch.object(swift, 'SwiftAPI')
    @mock.patch('ironic.drivers.modules.fake.FakeDeploy.prepare')
    def test__do_node_deploy_configdrive_swift_error(self, mock_prepare,
                                                     mock_swift):
        CONF.set_override('configdrive_use_object_store', True,
                          group='deploy')
        self._start_service()
        node = obj_utils.create_test_node(self.context, driver='fake-hardware',
                                          provision_state=states.DEPLOYING,
                                          target_provision_state=states.ACTIVE)
        task = task_manager.TaskManager(self.context, node.uuid)

        mock_swift.side_effect = exception.SwiftOperationError('error')
        self.assertRaises(exception.SwiftOperationError,
                          deployments.do_node_deploy, task,
                          self.service.conductor.id,
                          configdrive=b'fake config drive')
        node.refresh()
        self.assertEqual(states.DEPLOYFAIL, node.provision_state)
        self.assertEqual(states.ACTIVE, node.target_provision_state)
        self.assertIsNotNone(node.last_error)
        self.assertFalse(mock_prepare.called)

    @mock.patch('ironic.drivers.modules.fake.FakeDeploy.prepare')
    def test__do_node_deploy_configdrive_db_error(self, mock_prepare):
        self._start_service()
        node = obj_utils.create_test_node(self.context, driver='fake-hardware',
                                          provision_state=states.DEPLOYING,
                                          target_provision_state=states.ACTIVE)
        task = task_manager.TaskManager(self.context, node.uuid)
        task.node.save()
        expected_instance_info = dict(node.instance_info)
        with mock.patch.object(dbapi.IMPL, 'update_node') as mock_db:
            db_node = self.dbapi.get_node_by_uuid(node.uuid)
            mock_db.side_effect = [db_exception.DBDataError('DB error'),
                                   db_node, db_node, db_node]
            self.assertRaises(db_exception.DBDataError,
                              deployments.do_node_deploy, task,
                              self.service.conductor.id,
                              configdrive=b'fake config drive')
            expected_instance_info.update(configdrive=b'fake config drive')
            expected_calls = [
                mock.call(node.uuid,
                          {'version': mock.ANY,
                           'instance_info': expected_instance_info}),
                mock.call(node.uuid,
                          {'version': mock.ANY,
                           'last_error': mock.ANY}),
                mock.call(node.uuid,
                          {'version': mock.ANY,
                           'deploy_step': {},
                           'driver_internal_info': mock.ANY}),
                mock.call(node.uuid,
                          {'version': mock.ANY,
                           'provision_state': states.DEPLOYFAIL,
                           'target_provision_state': states.ACTIVE}),
            ]
            self.assertEqual(expected_calls, mock_db.mock_calls)
            self.assertFalse(mock_prepare.called)

    @mock.patch.object(deployments, '_store_configdrive', autospec=True)
    @mock.patch('ironic.drivers.modules.fake.FakeDeploy.prepare')
    def test__do_node_deploy_configdrive_unexpected_error(self, mock_prepare,
                                                          mock_store):
        self._start_service()
        node = obj_utils.create_test_node(self.context, driver='fake-hardware',
                                          provision_state=states.DEPLOYING,
                                          target_provision_state=states.ACTIVE)
        task = task_manager.TaskManager(self.context, node.uuid)

        mock_store.side_effect = RuntimeError('unexpected')
        self.assertRaises(RuntimeError,
                          deployments.do_node_deploy, task,
                          self.service.conductor.id,
                          configdrive=b'fake config drive')
        node.refresh()
        self.assertEqual(states.DEPLOYFAIL, node.provision_state)
        self.assertEqual(states.ACTIVE, node.target_provision_state)
        self.assertIsNotNone(node.last_error)
        self.assertFalse(mock_prepare.called)

    @mock.patch('ironic.drivers.modules.fake.FakeDeploy.deploy')
    def test__do_node_deploy_ok_2_old(self, mock_deploy):
        # TODO(rloo): delete this after the deprecation period for supporting
        # non deploy_steps.
        # Mocking FakeDeploy.deploy before starting the service, causes
        # it not to be a deploy_step.
        # NOTE(rloo): a different way of testing for the same thing as in
        # test__do_node_deploy_ok()
        self._start_service()
        # test when driver.deploy.deploy returns DEPLOYDONE
        mock_deploy.return_value = states.DEPLOYDONE
        node = obj_utils.create_test_node(self.context, driver='fake-hardware')
        task = task_manager.TaskManager(self.context, node.uuid)
        task.process_event('deploy')

        deployments.do_node_deploy(task, self.service.conductor.id)
        node.refresh()
        self.assertEqual(states.ACTIVE, node.provision_state)
        self.assertEqual(states.NOSTATE, node.target_provision_state)
        self.assertIsNone(node.last_error)
        mock_deploy.assert_called_once_with(mock.ANY)

    def test__do_node_deploy_ok_2(self):
        # NOTE(rloo): a different way of testing for the same thing as in
        # test__do_node_deploy_ok(). Instead of specifying the provision &
        # target_provision_states when creating the node, we call
        # task.process_event() to "set the stage" (err "states").
        self._start_service()
        with mock.patch.object(fake.FakeDeploy,
                               'deploy', autospec=True) as mock_deploy:
            # test when driver.deploy.deploy() returns None
            mock_deploy.return_value = None
            node = obj_utils.create_test_node(self.context,
                                              driver='fake-hardware')
            task = task_manager.TaskManager(self.context, node.uuid)
            task.process_event('deploy')

            deployments.do_node_deploy(task, self.service.conductor.id)
            node.refresh()
            self.assertEqual(states.ACTIVE, node.provision_state)
            self.assertEqual(states.NOSTATE, node.target_provision_state)
            self.assertIsNone(node.last_error)
            mock_deploy.assert_called_once_with(mock.ANY, mock.ANY)

    @mock.patch.object(deployments, 'do_next_deploy_step', autospec=True)
    @mock.patch.object(deployments, '_old_rest_of_do_node_deploy',
                       autospec=True)
    @mock.patch.object(conductor_steps, 'set_node_deployment_steps',
                       autospec=True)
    def test_do_node_deploy_deprecated(self, mock_set_steps, mock_old_way,
                                       mock_deploy_step):
        # TODO(rloo): no deploy steps; delete this when we remove support
        # for handling no deploy steps.
        self._start_service()
        node = obj_utils.create_test_node(self.context, driver='fake-hardware')
        task = task_manager.TaskManager(self.context, node.uuid)
        task.process_event('deploy')

        deployments.do_node_deploy(task, self.service.conductor.id)
        mock_set_steps.assert_called_once_with(task)
        mock_old_way.assert_called_once_with(task, self.service.conductor.id,
                                             True)
        self.assertFalse(mock_deploy_step.called)
        self.assertNotIn('deploy_steps', task.node.driver_internal_info)

    @mock.patch.object(deployments, 'do_next_deploy_step', autospec=True)
    @mock.patch.object(deployments, '_old_rest_of_do_node_deploy',
                       autospec=True)
    @mock.patch.object(conductor_steps, 'set_node_deployment_steps',
                       autospec=True)
    def test_do_node_deploy_steps(self, mock_set_steps, mock_old_way,
                                  mock_deploy_step):
        # these are not real steps...
        fake_deploy_steps = ['step1', 'step2']

        def add_steps(task):
            info = task.node.driver_internal_info
            info['deploy_steps'] = fake_deploy_steps
            task.node.driver_internal_info = info
            task.node.save()

        mock_set_steps.side_effect = add_steps
        self._start_service()
        node = obj_utils.create_test_node(self.context, driver='fake-hardware')
        task = task_manager.TaskManager(self.context, node.uuid)
        task.process_event('deploy')

        deployments.do_node_deploy(task, self.service.conductor.id)
        mock_set_steps.assert_called_once_with(task)
        self.assertFalse(mock_old_way.called)
        mock_set_steps.assert_called_once_with(task)
        self.assertEqual(fake_deploy_steps,
                         task.node.driver_internal_info['deploy_steps'])

    @mock.patch.object(deployments, 'do_next_deploy_step', autospec=True)
    @mock.patch.object(deployments, '_old_rest_of_do_node_deploy',
                       autospec=True)
    @mock.patch.object(conductor_steps, 'set_node_deployment_steps',
                       autospec=True)
    def test_do_node_deploy_steps_old_rpc(self, mock_set_steps, mock_old_way,
                                          mock_deploy_step):
        # TODO(rloo): old RPC; delete this when we remove support for drivers
        # with no deploy steps.
        CONF.set_override('pin_release_version', '11.0')
        # these are not real steps...
        fake_deploy_steps = ['step1', 'step2']

        def add_steps(task):
            info = task.node.driver_internal_info
            info['deploy_steps'] = fake_deploy_steps
            task.node.driver_internal_info = info
            task.node.save()

        mock_set_steps.side_effect = add_steps
        self._start_service()
        node = obj_utils.create_test_node(self.context, driver='fake-hardware')
        task = task_manager.TaskManager(self.context, node.uuid)
        task.process_event('deploy')

        deployments.do_node_deploy(task, self.service.conductor.id)
        mock_set_steps.assert_called_once_with(task)
        mock_old_way.assert_called_once_with(task, self.service.conductor.id,
                                             False)
        self.assertFalse(mock_deploy_step.called)
        self.assertNotIn('deploy_steps', task.node.driver_internal_info)

    @mock.patch.object(deployments, '_SEEN_NO_DEPLOY_STEP_DEPRECATIONS',
                       autospec=True)
    @mock.patch.object(deployments, 'LOG', autospec=True)
    @mock.patch('ironic.drivers.modules.fake.FakeDeploy.deploy', autospec=True)
    def test__old_rest_of_do_node_deploy_no_steps(self, mock_deploy, mock_log,
                                                  mock_deprecate):
        # TODO(rloo): no deploy steps; delete this when we remove support
        # for handling no deploy steps.
        mock_deprecate.__contains__.side_effect = [False, True]
        self._start_service()
        node = obj_utils.create_test_node(self.context, driver='fake-hardware')
        task = task_manager.TaskManager(self.context, node.uuid)
        task.process_event('deploy')

        deployments._old_rest_of_do_node_deploy(
            task, self.service.conductor.id, True)
        mock_deploy.assert_called_once_with(mock.ANY, task)
        self.assertTrue(mock_log.warning.called)
        self.assertEqual(self.service.conductor.id,
                         task.node.conductor_affinity)
        mock_deprecate.__contains__.assert_called_once_with('FakeDeploy')
        mock_deprecate.add.assert_called_once_with('FakeDeploy')

        # Make sure the deprecation warning isn't logged again
        mock_log.reset_mock()
        mock_deprecate.add.reset_mock()
        deployments._old_rest_of_do_node_deploy(
            task, self.service.conductor.id, True)
        self.assertFalse(mock_log.warning.called)
        mock_deprecate.__contains__.assert_has_calls(
            [mock.call('FakeDeploy'), mock.call('FakeDeploy')])
        self.assertFalse(mock_deprecate.add.called)

    @mock.patch.object(deployments, 'LOG', autospec=True)
    @mock.patch('ironic.drivers.modules.fake.FakeDeploy.deploy', autospec=True)
    def test__old_rest_of_do_node_deploy_has_steps(self, mock_deploy,
                                                   mock_log):
        # TODO(rloo): has steps but old RPC; delete this when we remove support
        # for handling no deploy steps.
        deployments._SEEN_NO_DEPLOY_STEP_DEPRECATIONS = set()
        self._start_service()
        node = obj_utils.create_test_node(self.context, driver='fake-hardware')
        task = task_manager.TaskManager(self.context, node.uuid)
        task.process_event('deploy')

        deployments._old_rest_of_do_node_deploy(
            task, self.service.conductor.id, False)
        mock_deploy.assert_called_once_with(mock.ANY, task)
        self.assertFalse(mock_log.warning.called)
        self.assertEqual(self.service.conductor.id,
                         task.node.conductor_affinity)

    @mock.patch('ironic.conductor.deployments._start_console_in_deploy',
                autospec=True)
    @mock.patch('ironic.drivers.modules.fake.FakeDeploy.deploy', autospec=True)
    def test__old_rest_of_do_node_deploy_console(self, mock_deploy,
                                                 mock_console):
        self._start_service()
        node = obj_utils.create_test_node(self.context, driver='fake-hardware')
        task = task_manager.TaskManager(self.context, node.uuid)
        task.process_event('deploy')
        mock_deploy.return_value = states.DEPLOYDONE

        deployments._old_rest_of_do_node_deploy(
            task, self.service.conductor.id, True)
        mock_deploy.assert_called_once_with(mock.ANY, task)
        mock_console.assert_called_once_with(task)
        self.assertEqual(self.service.conductor.id,
                         task.node.conductor_affinity)


@mgr_utils.mock_record_keepalive
class DoNextDeployStepTestCase(mgr_utils.ServiceSetUpMixin,
                               db_base.DbTestCase):
    def setUp(self):
        super(DoNextDeployStepTestCase, self).setUp()
        self.deploy_start = {
            'step': 'deploy_start', 'priority': 50, 'interface': 'deploy'}
        self.deploy_end = {
            'step': 'deploy_end', 'priority': 20, 'interface': 'deploy'}
        self.deploy_steps = [self.deploy_start, self.deploy_end]

    @mock.patch.object(deployments, 'LOG', autospec=True)
    def test__do_next_deploy_step_none(self, mock_log):
        self._start_service()
        node = obj_utils.create_test_node(self.context, driver='fake-hardware')
        task = task_manager.TaskManager(self.context, node.uuid)
        task.process_event('deploy')

        deployments.do_next_deploy_step(task, None, self.service.conductor.id)

        node.refresh()
        self.assertEqual(states.ACTIVE, node.provision_state)
        self.assertEqual(2, mock_log.info.call_count)

    @mock.patch('ironic.drivers.modules.fake.FakeDeploy.execute_deploy_step',
                autospec=True)
    def test__do_next_deploy_step_async(self, mock_execute):
        driver_internal_info = {'deploy_step_index': None,
                                'deploy_steps': self.deploy_steps}
        self._start_service()
        node = obj_utils.create_test_node(
            self.context, driver='fake-hardware',
            driver_internal_info=driver_internal_info,
            deploy_step={})
        mock_execute.return_value = states.DEPLOYWAIT
        expected_first_step = node.driver_internal_info['deploy_steps'][0]
        task = task_manager.TaskManager(self.context, node.uuid)
        task.process_event('deploy')

        deployments.do_next_deploy_step(task, 0, self.service.conductor.id)

        node.refresh()
        self.assertEqual(states.DEPLOYWAIT, node.provision_state)
        self.assertEqual(states.ACTIVE, node.target_provision_state)
        self.assertEqual(expected_first_step, node.deploy_step)
        self.assertEqual(0, node.driver_internal_info['deploy_step_index'])
        self.assertEqual(self.service.conductor.id, node.conductor_affinity)
        mock_execute.assert_called_once_with(mock.ANY, task,
                                             self.deploy_steps[0])

    @mock.patch('ironic.drivers.modules.fake.FakeDeploy.execute_deploy_step',
                autospec=True)
    def test__do_next_deploy_step_continue_from_last_step(self, mock_execute):
        # Resume an in-progress deploy after the first async step
        driver_internal_info = {'deploy_step_index': 0,
                                'deploy_steps': self.deploy_steps}
        self._start_service()
        node = obj_utils.create_test_node(
            self.context, driver='fake-hardware',
            provision_state=states.DEPLOYWAIT,
            target_provision_state=states.ACTIVE,
            driver_internal_info=driver_internal_info,
            deploy_step=self.deploy_steps[0])
        mock_execute.return_value = states.DEPLOYWAIT

        task = task_manager.TaskManager(self.context, node.uuid)
        task.process_event('resume')

        deployments.do_next_deploy_step(task, 1, self.service.conductor.id)
        node.refresh()

        self.assertEqual(states.DEPLOYWAIT, node.provision_state)
        self.assertEqual(states.ACTIVE, node.target_provision_state)
        self.assertEqual(self.deploy_steps[1], node.deploy_step)
        self.assertEqual(1, node.driver_internal_info['deploy_step_index'])
        mock_execute.assert_called_once_with(mock.ANY, task,
                                             self.deploy_steps[1])

    @mock.patch('ironic.drivers.modules.fake.FakeConsole.start_console',
                autospec=True)
    @mock.patch('ironic.drivers.modules.fake.FakeDeploy.execute_deploy_step',
                autospec=True)
    def _test__do_next_deploy_step_last_step_done(self, mock_execute,
                                                  mock_console,
                                                  console_enabled=False,
                                                  console_error=False):
        # Resume where last_step is the last deploy step that was executed
        driver_internal_info = {'deploy_step_index': 1,
                                'deploy_steps': self.deploy_steps}
        self._start_service()
        node = obj_utils.create_test_node(
            self.context, driver='fake-hardware',
            provision_state=states.DEPLOYWAIT,
            target_provision_state=states.ACTIVE,
            driver_internal_info=driver_internal_info,
            deploy_step=self.deploy_steps[1],
            console_enabled=console_enabled)
        mock_execute.return_value = None
        if console_error:
            mock_console.side_effect = exception.ConsoleError()

        task = task_manager.TaskManager(self.context, node.uuid)
        task.process_event('resume')

        deployments.do_next_deploy_step(task, None, self.service.conductor.id)
        node.refresh()
        # Deploying should be complete without calling additional steps
        self.assertEqual(states.ACTIVE, node.provision_state)
        self.assertEqual(states.NOSTATE, node.target_provision_state)
        self.assertEqual({}, node.deploy_step)
        self.assertNotIn('deploy_step_index', node.driver_internal_info)
        self.assertIsNone(node.driver_internal_info['deploy_steps'])
        self.assertFalse(mock_execute.called)
        if console_enabled:
            mock_console.assert_called_once_with(mock.ANY, task)
        else:
            self.assertFalse(mock_console.called)

    def test__do_next_deploy_step_last_step_done(self):
        self._test__do_next_deploy_step_last_step_done()

    def test__do_next_deploy_step_last_step_done_with_console(self):
        self._test__do_next_deploy_step_last_step_done(console_enabled=True)

    def test__do_next_deploy_step_last_step_done_with_console_error(self):
        self._test__do_next_deploy_step_last_step_done(console_enabled=True,
                                                       console_error=True)

    @mock.patch('ironic.drivers.modules.fake.FakeDeploy.execute_deploy_step',
                autospec=True)
    def test__do_next_deploy_step_all(self, mock_execute):
        # Run all steps from start to finish (all synchronous)
        driver_internal_info = {'deploy_step_index': None,
                                'deploy_steps': self.deploy_steps,
                                'agent_url': 'url'}
        self._start_service()
        node = obj_utils.create_test_node(
            self.context, driver='fake-hardware',
            driver_internal_info=driver_internal_info,
            deploy_step={})
        mock_execute.return_value = None

        task = task_manager.TaskManager(self.context, node.uuid)
        task.process_event('deploy')

        deployments.do_next_deploy_step(task, 1, self.service.conductor.id)

        # Deploying should be complete
        node.refresh()
        self.assertEqual(states.ACTIVE, node.provision_state)
        self.assertEqual(states.NOSTATE, node.target_provision_state)
        self.assertEqual({}, node.deploy_step)
        self.assertNotIn('deploy_step_index', node.driver_internal_info)
        self.assertIsNone(node.driver_internal_info['deploy_steps'])
        mock_execute.assert_has_calls = [mock.call(self.deploy_steps[0]),
                                         mock.call(self.deploy_steps[1])]
        self.assertNotIn('agent_url', node.driver_internal_info)

    @mock.patch.object(conductor_utils, 'LOG', autospec=True)
    @mock.patch('ironic.drivers.modules.fake.FakeDeploy.execute_deploy_step',
                autospec=True)
    def _do_next_deploy_step_execute_fail(self, exc, traceback,
                                          mock_execute, mock_log):
        # When a deploy step fails, go to DEPLOYFAIL
        driver_internal_info = {'deploy_step_index': None,
                                'deploy_steps': self.deploy_steps}
        self._start_service()
        node = obj_utils.create_test_node(
            self.context, driver='fake-hardware',
            driver_internal_info=driver_internal_info,
            deploy_step={})
        mock_execute.side_effect = exc

        task = task_manager.TaskManager(self.context, node.uuid)
        task.process_event('deploy')

        deployments.do_next_deploy_step(task, 0, self.service.conductor.id)

        # Make sure we go to DEPLOYFAIL, clear deploy_steps
        node.refresh()
        self.assertEqual(states.DEPLOYFAIL, node.provision_state)
        self.assertEqual(states.ACTIVE, node.target_provision_state)
        self.assertEqual({}, node.deploy_step)
        self.assertNotIn('deploy_step_index', node.driver_internal_info)
        self.assertIsNotNone(node.last_error)
        self.assertFalse(node.maintenance)
        mock_execute.assert_called_once_with(mock.ANY, mock.ANY,
                                             self.deploy_steps[0])
        mock_log.error.assert_called_once_with(mock.ANY, exc_info=traceback)

    def test_do_next_deploy_step_execute_ironic_exception(self):
        self._do_next_deploy_step_execute_fail(
            exception.IronicException('foo'), False)

    def test_do_next_deploy_step_execute_exception(self):
        self._do_next_deploy_step_execute_fail(Exception('foo'), True)

    @mock.patch('ironic.drivers.modules.fake.FakeDeploy.execute_deploy_step',
                autospec=True)
    def test_do_next_deploy_step_no_steps(self, mock_execute):

        self._start_service()
        for info in ({'deploy_steps': None, 'deploy_step_index': None},
                     {'deploy_steps': None}):
            # Resume where there are no steps, should be a noop
            node = obj_utils.create_test_node(
                self.context, driver='fake-hardware',
                uuid=uuidutils.generate_uuid(),
                last_error=None,
                driver_internal_info=info,
                deploy_step={})

            task = task_manager.TaskManager(self.context, node.uuid)
            task.process_event('deploy')

            deployments.do_next_deploy_step(task, None,
                                            self.service.conductor.id)

            # Deploying should be complete without calling additional steps
            node.refresh()
            self.assertEqual(states.ACTIVE, node.provision_state)
            self.assertEqual(states.NOSTATE, node.target_provision_state)
            self.assertEqual({}, node.deploy_step)
            self.assertNotIn('deploy_step_index', node.driver_internal_info)
            self.assertFalse(mock_execute.called)
            mock_execute.reset_mock()

    @mock.patch('ironic.drivers.modules.fake.FakeDeploy.execute_deploy_step',
                autospec=True)
    def test_do_next_deploy_step_bad_step_return_value(self, mock_execute):
        # When a deploy step fails, go to DEPLOYFAIL
        self._start_service()
        node = obj_utils.create_test_node(
            self.context, driver='fake-hardware',
            driver_internal_info={'deploy_steps': self.deploy_steps,
                                  'deploy_step_index': None},
            deploy_step={})
        mock_execute.return_value = "foo"

        task = task_manager.TaskManager(self.context, node.uuid)
        task.process_event('deploy')

        deployments.do_next_deploy_step(task, 0, self.service.conductor.id)

        # Make sure we go to DEPLOYFAIL, clear deploy_steps
        node.refresh()
        self.assertEqual(states.DEPLOYFAIL, node.provision_state)
        self.assertEqual(states.ACTIVE, node.target_provision_state)
        self.assertEqual({}, node.deploy_step)
        self.assertNotIn('deploy_step_index', node.driver_internal_info)
        self.assertIsNotNone(node.last_error)
        self.assertFalse(node.maintenance)
        mock_execute.assert_called_once_with(mock.ANY, mock.ANY,
                                             self.deploy_steps[0])

    @mock.patch('ironic.drivers.modules.fake.FakeDeploy.execute_deploy_step',
                autospec=True)
    def test_do_next_deploy_step_oob_reboot(self, mock_execute):
        # When a deploy step fails, go to DEPLOYWAIT
        tgt_prov_state = states.ACTIVE

        self._start_service()
        node = obj_utils.create_test_node(
            self.context, driver='fake-hardware',
            provision_state=states.DEPLOYING,
            target_provision_state=tgt_prov_state,
            last_error=None,
            driver_internal_info={'deploy_steps': self.deploy_steps,
                                  'deploy_step_index': None,
                                  'deployment_reboot': True},
            clean_step={})
        mock_execute.side_effect = exception.AgentConnectionFailed(
            reason='failed')

        with task_manager.acquire(
                self.context, node.uuid, shared=False) as task:
            deployments.do_next_deploy_step(task, 0, mock.ANY)

        self._stop_service()
        node.refresh()

        # Make sure we go to CLEANWAIT
        self.assertEqual(states.DEPLOYWAIT, node.provision_state)
        self.assertEqual(tgt_prov_state, node.target_provision_state)
        self.assertEqual(self.deploy_steps[0], node.deploy_step)
        self.assertEqual(0, node.driver_internal_info['deploy_step_index'])
        self.assertFalse(node.driver_internal_info['skip_current_deploy_step'])
        mock_execute.assert_called_once_with(
            mock.ANY, mock.ANY, self.deploy_steps[0])

    @mock.patch('ironic.drivers.modules.fake.FakeDeploy.execute_deploy_step',
                autospec=True)
    def test_do_next_deploy_step_oob_reboot_fail(self, mock_execute):
        # When a deploy step fails with no reboot requested go to DEPLOYFAIL
        tgt_prov_state = states.ACTIVE

        self._start_service()
        node = obj_utils.create_test_node(
            self.context, driver='fake-hardware',
            provision_state=states.DEPLOYING,
            target_provision_state=tgt_prov_state,
            last_error=None,
            driver_internal_info={'deploy_steps': self.deploy_steps,
                                  'deploy_step_index': None},
            deploy_step={})
        mock_execute.side_effect = exception.AgentConnectionFailed(
            reason='failed')

        with task_manager.acquire(
                self.context, node.uuid, shared=False) as task:
            deployments.do_next_deploy_step(task, 0, mock.ANY)

        self._stop_service()
        node.refresh()

        # Make sure we go to DEPLOYFAIL, clear deploy_steps
        self.assertEqual(states.DEPLOYFAIL, node.provision_state)
        self.assertEqual(tgt_prov_state, node.target_provision_state)
        self.assertEqual({}, node.deploy_step)
        self.assertNotIn('deploy_step_index', node.driver_internal_info)
        self.assertNotIn('skip_current_deploy_step', node.driver_internal_info)
        self.assertIsNotNone(node.last_error)
        mock_execute.assert_called_once_with(
            mock.ANY, mock.ANY, self.deploy_steps[0])


@mock.patch.object(swift, 'SwiftAPI')
class StoreConfigDriveTestCase(db_base.DbTestCase):

    def setUp(self):
        super(StoreConfigDriveTestCase, self).setUp()
        self.node = obj_utils.create_test_node(self.context,
                                               driver='fake-hardware',
                                               instance_info=None)

    def test_store_configdrive(self, mock_swift):
        deployments._store_configdrive(self.node, 'foo')
        expected_instance_info = {'configdrive': 'foo'}
        self.node.refresh()
        self.assertEqual(expected_instance_info, self.node.instance_info)
        self.assertFalse(mock_swift.called)

    def test_store_configdrive_swift(self, mock_swift):
        container_name = 'foo_container'
        timeout = 123
        expected_obj_name = 'configdrive-%s' % self.node.uuid
        expected_obj_header = {'X-Delete-After': str(timeout)}
        expected_instance_info = {'configdrive': 'http://1.2.3.4'}

        # set configs and mocks
        CONF.set_override('configdrive_use_object_store', True,
                          group='deploy')
        CONF.set_override('configdrive_swift_container', container_name,
                          group='conductor')
        CONF.set_override('deploy_callback_timeout', timeout,
                          group='conductor')
        mock_swift.return_value.get_temp_url.return_value = 'http://1.2.3.4'

        deployments._store_configdrive(self.node, b'foo')

        mock_swift.assert_called_once_with()
        mock_swift.return_value.create_object.assert_called_once_with(
            container_name, expected_obj_name, mock.ANY,
            object_headers=expected_obj_header)
        mock_swift.return_value.get_temp_url.assert_called_once_with(
            container_name, expected_obj_name, timeout)
        self.node.refresh()
        self.assertEqual(expected_instance_info, self.node.instance_info)

    def test_store_configdrive_swift_no_deploy_timeout(self, mock_swift):
        container_name = 'foo_container'
        expected_obj_name = 'configdrive-%s' % self.node.uuid
        expected_obj_header = {'X-Delete-After': '1200'}
        expected_instance_info = {'configdrive': 'http://1.2.3.4'}

        # set configs and mocks
        CONF.set_override('configdrive_use_object_store', True,
                          group='deploy')
        CONF.set_override('configdrive_swift_container', container_name,
                          group='conductor')
        CONF.set_override('configdrive_swift_temp_url_duration', 1200,
                          group='conductor')
        CONF.set_override('deploy_callback_timeout', 0,
                          group='conductor')
        mock_swift.return_value.get_temp_url.return_value = 'http://1.2.3.4'

        deployments._store_configdrive(self.node, b'foo')

        mock_swift.assert_called_once_with()
        mock_swift.return_value.create_object.assert_called_once_with(
            container_name, expected_obj_name, mock.ANY,
            object_headers=expected_obj_header)
        mock_swift.return_value.get_temp_url.assert_called_once_with(
            container_name, expected_obj_name, 1200)
        self.node.refresh()
        self.assertEqual(expected_instance_info, self.node.instance_info)

    def test_store_configdrive_swift_no_deploy_timeout_fallback(self,
                                                                mock_swift):
        container_name = 'foo_container'
        expected_obj_name = 'configdrive-%s' % self.node.uuid
        expected_obj_header = {'X-Delete-After': '1800'}
        expected_instance_info = {'configdrive': 'http://1.2.3.4'}

        # set configs and mocks
        CONF.set_override('configdrive_use_object_store', True,
                          group='deploy')
        CONF.set_override('configdrive_swift_container', container_name,
                          group='conductor')
        CONF.set_override('deploy_callback_timeout', 0,
                          group='conductor')
        mock_swift.return_value.get_temp_url.return_value = 'http://1.2.3.4'

        deployments._store_configdrive(self.node, b'foo')

        mock_swift.assert_called_once_with()
        mock_swift.return_value.create_object.assert_called_once_with(
            container_name, expected_obj_name, mock.ANY,
            object_headers=expected_obj_header)
        mock_swift.return_value.get_temp_url.assert_called_once_with(
            container_name, expected_obj_name, 1800)
        self.node.refresh()
        self.assertEqual(expected_instance_info, self.node.instance_info)
