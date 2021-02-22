# coding=utf-8

# Copyright 2013 Hewlett-Packard Development Company, L.P.
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

"""Tests for :class:`ironic.conductor.task_manager`."""

import futurist
import mock
from oslo_utils import uuidutils

from ironic.common import driver_factory
from ironic.common import exception
from ironic.common import fsm
from ironic.common import states
from ironic.conductor import notification_utils
from ironic.conductor import task_manager
from ironic import objects
from ironic.objects import fields
from ironic.tests import base as tests_base
from ironic.tests.unit.db import base as db_base
from ironic.tests.unit.objects import utils as obj_utils


@mock.patch.object(objects.Node, 'get')
@mock.patch.object(objects.Node, 'release')
@mock.patch.object(objects.Node, 'reserve')
@mock.patch.object(driver_factory, 'build_driver_for_task')
@mock.patch.object(objects.Port, 'list_by_node_id')
@mock.patch.object(objects.Portgroup, 'list_by_node_id')
@mock.patch.object(objects.VolumeConnector, 'list_by_node_id')
@mock.patch.object(objects.VolumeTarget, 'list_by_node_id')
class TaskManagerTestCase(db_base.DbTestCase):
    def setUp(self):
        super(TaskManagerTestCase, self).setUp()
        self.host = 'test-host'
        self.config(host=self.host)
        self.config(node_locked_retry_attempts=1, group='conductor')
        self.config(node_locked_retry_interval=0, group='conductor')
        self.node = obj_utils.create_test_node(self.context)
        self.future_mock = mock.Mock(spec=['cancel', 'add_done_callback'])

    def test_excl_lock(self, get_voltgt_mock, get_volconn_mock,
                       get_portgroups_mock, get_ports_mock,
                       build_driver_mock, reserve_mock, release_mock,
                       node_get_mock):
        reserve_mock.return_value = self.node
        with task_manager.TaskManager(self.context, 'fake-node-id') as task:
            self.assertEqual(self.context, task.context)
            self.assertEqual(self.node, task.node)
            self.assertEqual(get_ports_mock.return_value, task.ports)
            self.assertEqual(get_portgroups_mock.return_value, task.portgroups)
            self.assertEqual(get_volconn_mock.return_value,
                             task.volume_connectors)
            self.assertEqual(get_voltgt_mock.return_value, task.volume_targets)
            self.assertEqual(build_driver_mock.return_value, task.driver)
            self.assertFalse(task.shared)
            build_driver_mock.assert_called_once_with(task)

        node_get_mock.assert_called_once_with(self.context, 'fake-node-id')
        reserve_mock.assert_called_once_with(self.context, self.host,
                                             'fake-node-id')
        get_ports_mock.assert_called_once_with(self.context, self.node.id)
        get_portgroups_mock.assert_called_once_with(self.context, self.node.id)
        get_volconn_mock.assert_called_once_with(self.context, self.node.id)
        get_voltgt_mock.assert_called_once_with(self.context, self.node.id)
        release_mock.assert_called_once_with(self.context, self.host,
                                             self.node.id)

    def test_no_driver(self, get_voltgt_mock, get_volconn_mock,
                       get_portgroups_mock, get_ports_mock,
                       build_driver_mock, reserve_mock, release_mock,
                       node_get_mock):
        reserve_mock.return_value = self.node
        with task_manager.TaskManager(self.context, 'fake-node-id',
                                      load_driver=False) as task:
            self.assertEqual(self.context, task.context)
            self.assertEqual(self.node, task.node)
            self.assertEqual(get_ports_mock.return_value, task.ports)
            self.assertEqual(get_portgroups_mock.return_value, task.portgroups)
            self.assertEqual(get_volconn_mock.return_value,
                             task.volume_connectors)
            self.assertEqual(get_voltgt_mock.return_value, task.volume_targets)
            self.assertIsNone(task.driver)
            self.assertFalse(task.shared)
        self.assertFalse(build_driver_mock.called)

    def test_excl_nested_acquire(
            self, get_voltgt_mock, get_volconn_mock, get_portgroups_mock,
            get_ports_mock, build_driver_mock,
            reserve_mock, release_mock, node_get_mock):
        node2 = obj_utils.create_test_node(self.context,
                                           uuid=uuidutils.generate_uuid(),
                                           driver='fake-hardware')

        reserve_mock.return_value = self.node
        get_ports_mock.return_value = mock.sentinel.ports1
        get_portgroups_mock.return_value = mock.sentinel.portgroups1
        get_volconn_mock.return_value = mock.sentinel.volconn1
        get_voltgt_mock.return_value = mock.sentinel.voltgt1
        build_driver_mock.return_value = mock.sentinel.driver1

        # Note(arne_wiebalck): Force loading of lazy-loaded properties.
        def _eval_all(task):
            return task.ports, task.portgroups, task.volume_targets, \
                task.volume_connectors

        with task_manager.TaskManager(self.context, 'node-id1') as task:
            _eval_all(task)
            reserve_mock.return_value = node2
            get_ports_mock.return_value = mock.sentinel.ports2
            get_portgroups_mock.return_value = mock.sentinel.portgroups2
            get_volconn_mock.return_value = mock.sentinel.volconn2
            get_voltgt_mock.return_value = mock.sentinel.voltgt2
            build_driver_mock.return_value = mock.sentinel.driver2
            with task_manager.TaskManager(self.context, 'node-id2') as task2:
                _eval_all(task2)
                self.assertEqual(self.context, task.context)
                self.assertEqual(self.node, task.node)
                self.assertEqual(mock.sentinel.ports1, task.ports)
                self.assertEqual(mock.sentinel.portgroups1, task.portgroups)
                self.assertEqual(mock.sentinel.volconn1,
                                 task.volume_connectors)
                self.assertEqual(mock.sentinel.voltgt1, task.volume_targets)
                self.assertEqual(mock.sentinel.driver1, task.driver)
                self.assertFalse(task.shared)
                self.assertEqual(self.context, task2.context)
                self.assertEqual(node2, task2.node)
                self.assertEqual(mock.sentinel.ports2, task2.ports)
                self.assertEqual(mock.sentinel.portgroups2, task2.portgroups)
                self.assertEqual(mock.sentinel.volconn2,
                                 task2.volume_connectors)
                self.assertEqual(mock.sentinel.voltgt2, task2.volume_targets)
                self.assertEqual(mock.sentinel.driver2, task2.driver)
                self.assertFalse(task2.shared)

                self.assertEqual([mock.call(task), mock.call(task2)],
                                 build_driver_mock.call_args_list)

        self.assertEqual([mock.call(self.context, 'node-id1'),
                          mock.call(self.context, 'node-id2')],
                         node_get_mock.call_args_list)
        self.assertEqual([mock.call(self.context, self.host, 'node-id1'),
                          mock.call(self.context, self.host, 'node-id2')],
                         reserve_mock.call_args_list)
        self.assertEqual([mock.call(self.context, self.node.id),
                          mock.call(self.context, node2.id)],
                         get_ports_mock.call_args_list)
        # release should be in reverse order
        self.assertEqual([mock.call(self.context, self.host, node2.id),
                          mock.call(self.context, self.host, self.node.id)],
                         release_mock.call_args_list)

    def test_excl_lock_exception_then_lock(
            self, get_voltgt_mock, get_volconn_mock, get_portgroups_mock,
            get_ports_mock, build_driver_mock,
            reserve_mock, release_mock, node_get_mock):
        retry_attempts = 3
        self.config(node_locked_retry_attempts=retry_attempts,
                    group='conductor')

        # Fail on the first lock attempt, succeed on the second.
        reserve_mock.side_effect = [exception.NodeLocked(node='foo',
                                                         host='foo'),
                                    self.node]

        with task_manager.TaskManager(self.context, 'fake-node-id') as task:
            self.assertFalse(task.shared)

        expected_calls = [mock.call(self.context, self.host,
                                    'fake-node-id')] * 2
        reserve_mock.assert_has_calls(expected_calls)
        self.assertEqual(2, reserve_mock.call_count)

    def test_excl_lock_exception_no_retries(
            self, get_voltgt_mock, get_volconn_mock, get_portgroups_mock,
            get_ports_mock, build_driver_mock,
            reserve_mock, release_mock, node_get_mock):
        retry_attempts = 3
        self.config(node_locked_retry_attempts=retry_attempts,
                    group='conductor')

        # Fail on the first lock attempt, succeed on the second.
        reserve_mock.side_effect = [exception.NodeLocked(node='foo',
                                                         host='foo'),
                                    self.node]

        self.assertRaises(exception.NodeLocked,
                          task_manager.TaskManager,
                          self.context,
                          'fake-node-id',
                          retry=False)

        reserve_mock.assert_called_once_with(self.context, self.host,
                                             'fake-node-id')

    def test_excl_lock_reserve_exception(
            self, get_voltgt_mock, get_volconn_mock, get_portgroups_mock,
            get_ports_mock, build_driver_mock,
            reserve_mock, release_mock, node_get_mock):
        retry_attempts = 3
        self.config(node_locked_retry_attempts=retry_attempts,
                    group='conductor')
        reserve_mock.side_effect = exception.NodeLocked(node='foo',
                                                        host='foo')

        self.assertRaises(exception.NodeLocked,
                          task_manager.TaskManager,
                          self.context,
                          'fake-node-id')
        node_get_mock.assert_called_with(self.context, 'fake-node-id')
        reserve_mock.assert_called_with(self.context, self.host,
                                        'fake-node-id')
        self.assertEqual(retry_attempts, reserve_mock.call_count)
        self.assertFalse(get_ports_mock.called)
        self.assertFalse(get_portgroups_mock.called)
        self.assertFalse(get_volconn_mock.called)
        self.assertFalse(get_voltgt_mock.called)
        self.assertFalse(build_driver_mock.called)
        self.assertFalse(release_mock.called)

    def test_excl_lock_get_ports_exception(
            self, get_voltgt_mock, get_volconn_mock, get_portgroups_mock,
            get_ports_mock, build_driver_mock,
            reserve_mock, release_mock, node_get_mock):
        reserve_mock.return_value = self.node
        get_ports_mock.side_effect = exception.IronicException('foo')

        # Note(arne_wiebalck): Force loading of lazy-loaded properties.
        def _eval_ports(task):
            return task.ports

        with task_manager.TaskManager(self.context, 'fake-node-id') as task:
            self.assertRaises(exception.IronicException, _eval_ports, task)

        node_get_mock.assert_called_once_with(self.context, 'fake-node-id')
        reserve_mock.assert_called_once_with(self.context, self.host,
                                             'fake-node-id')
        get_ports_mock.assert_called_once_with(self.context, self.node.id)
        self.assertTrue(build_driver_mock.called)
        release_mock.assert_called_once_with(self.context, self.host,
                                             self.node.id)

    def test_excl_lock_get_portgroups_exception(
            self, get_voltgt_mock, get_volconn_mock, get_portgroups_mock,
            get_ports_mock, build_driver_mock,
            reserve_mock, release_mock, node_get_mock):
        reserve_mock.return_value = self.node
        get_portgroups_mock.side_effect = exception.IronicException('foo')

        # Note(arne_wiebalck): Force loading of lazy-loaded properties.
        def _eval_portgroups(task):
            return task.portgroups

        with task_manager.TaskManager(self.context, 'fake-node-id') as task:
            self.assertRaises(exception.IronicException, _eval_portgroups,
                              task)

        node_get_mock.assert_called_once_with(self.context, 'fake-node-id')
        reserve_mock.assert_called_once_with(self.context, self.host,
                                             'fake-node-id')
        get_portgroups_mock.assert_called_once_with(self.context, self.node.id)
        self.assertTrue(build_driver_mock.called)
        release_mock.assert_called_once_with(self.context, self.host,
                                             self.node.id)

    def test_excl_lock_get_volconn_exception(
            self, get_voltgt_mock, get_volconn_mock, get_portgroups_mock,
            get_ports_mock, build_driver_mock,
            reserve_mock, release_mock, node_get_mock):
        reserve_mock.return_value = self.node
        get_volconn_mock.side_effect = exception.IronicException('foo')

        # Note(arne_wiebalck): Force loading of lazy-loaded properties.
        def _eval_volconn(task):
            return task.volume_connectors

        with task_manager.TaskManager(self.context, 'fake-node-id') as task:
            self.assertRaises(exception.IronicException, _eval_volconn,
                              task)

        reserve_mock.assert_called_once_with(self.context, self.host,
                                             'fake-node-id')
        get_volconn_mock.assert_called_once_with(self.context, self.node.id)
        self.assertTrue(build_driver_mock.called)
        release_mock.assert_called_once_with(self.context, self.host,
                                             self.node.id)
        node_get_mock.assert_called_once_with(self.context, 'fake-node-id')

    def test_excl_lock_get_voltgt_exception(
            self, get_voltgt_mock, get_volconn_mock, get_portgroups_mock,
            get_ports_mock, build_driver_mock,
            reserve_mock, release_mock, node_get_mock):
        reserve_mock.return_value = self.node
        get_voltgt_mock.side_effect = exception.IronicException('foo')

        # Note(arne_wiebalck): Force loading of lazy-loaded properties.
        def _eval_voltgt(task):
            return task.volume_targets

        with task_manager.TaskManager(self.context, 'fake-node-id') as task:
            self.assertRaises(exception.IronicException, _eval_voltgt, task)

        reserve_mock.assert_called_once_with(self.context, self.host,
                                             'fake-node-id')
        get_voltgt_mock.assert_called_once_with(self.context, self.node.id)
        self.assertTrue(build_driver_mock.called)
        release_mock.assert_called_once_with(self.context, self.host,
                                             self.node.id)
        node_get_mock.assert_called_once_with(self.context, 'fake-node-id')

    def test_excl_lock_build_driver_exception(
            self, get_voltgt_mock, get_volconn_mock, get_portgroups_mock,
            get_ports_mock, build_driver_mock,
            reserve_mock, release_mock, node_get_mock):
        reserve_mock.return_value = self.node
        build_driver_mock.side_effect = (
            exception.DriverNotFound(driver_name='foo'))

        self.assertRaises(exception.DriverNotFound,
                          task_manager.TaskManager,
                          self.context,
                          'fake-node-id')

        node_get_mock.assert_called_once_with(self.context, 'fake-node-id')
        reserve_mock.assert_called_once_with(self.context, self.host,
                                             'fake-node-id')
        self.assertFalse(get_ports_mock.called)
        self.assertFalse(get_portgroups_mock.called)
        self.assertFalse(get_volconn_mock.called)
        self.assertFalse(get_voltgt_mock.called)
        build_driver_mock.assert_called_once_with(mock.ANY)
        release_mock.assert_called_once_with(self.context, self.host,
                                             self.node.id)

    def test_shared_lock(
            self, get_voltgt_mock, get_volconn_mock, get_portgroups_mock,
            get_ports_mock, build_driver_mock,
            reserve_mock, release_mock, node_get_mock):
        node_get_mock.return_value = self.node
        with task_manager.TaskManager(self.context, 'fake-node-id',
                                      shared=True) as task:
            self.assertEqual(self.context, task.context)
            self.assertEqual(self.node, task.node)
            self.assertEqual(get_ports_mock.return_value, task.ports)
            self.assertEqual(get_portgroups_mock.return_value, task.portgroups)
            self.assertEqual(get_volconn_mock.return_value,
                             task.volume_connectors)
            self.assertEqual(get_voltgt_mock.return_value, task.volume_targets)
            self.assertEqual(build_driver_mock.return_value, task.driver)
            self.assertTrue(task.shared)

            build_driver_mock.assert_called_once_with(task)

        self.assertFalse(reserve_mock.called)
        self.assertFalse(release_mock.called)
        node_get_mock.assert_called_once_with(self.context, 'fake-node-id')
        get_ports_mock.assert_called_once_with(self.context, self.node.id)
        get_portgroups_mock.assert_called_once_with(self.context, self.node.id)
        get_volconn_mock.assert_called_once_with(self.context, self.node.id)
        get_voltgt_mock.assert_called_once_with(self.context, self.node.id)

    def test_shared_lock_node_get_exception(
            self, get_voltgt_mock, get_volconn_mock, get_portgroups_mock,
            get_ports_mock, build_driver_mock,
            reserve_mock, release_mock, node_get_mock):
        node_get_mock.side_effect = exception.NodeNotFound(node='foo')

        self.assertRaises(exception.NodeNotFound,
                          task_manager.TaskManager,
                          self.context,
                          'fake-node-id',
                          shared=True)

        self.assertFalse(reserve_mock.called)
        self.assertFalse(release_mock.called)
        node_get_mock.assert_called_once_with(self.context, 'fake-node-id')
        self.assertFalse(get_ports_mock.called)
        self.assertFalse(get_portgroups_mock.called)
        self.assertFalse(get_volconn_mock.called)
        self.assertFalse(get_voltgt_mock.called)
        self.assertFalse(build_driver_mock.called)

    def test_shared_lock_get_ports_exception(
            self, get_voltgt_mock, get_volconn_mock, get_portgroups_mock,
            get_ports_mock, build_driver_mock,
            reserve_mock, release_mock, node_get_mock):
        node_get_mock.return_value = self.node
        get_ports_mock.side_effect = exception.IronicException('foo')

        # Note(arne_wiebalck): Force loading of lazy-loaded properties.
        def _eval_ports(task):
            return task.ports

        with task_manager.TaskManager(self.context, 'fake-node-id',
                                      shared=True) as task:
            self.assertRaises(exception.IronicException, _eval_ports, task)

        self.assertFalse(reserve_mock.called)
        self.assertFalse(release_mock.called)
        node_get_mock.assert_called_once_with(self.context, 'fake-node-id')
        get_ports_mock.assert_called_once_with(self.context, self.node.id)
        self.assertTrue(build_driver_mock.called)

    def test_shared_lock_get_portgroups_exception(
            self, get_voltgt_mock, get_volconn_mock, get_portgroups_mock,
            get_ports_mock, build_driver_mock,
            reserve_mock, release_mock, node_get_mock):
        node_get_mock.return_value = self.node
        get_portgroups_mock.side_effect = exception.IronicException('foo')

        # Note(arne_wiebalck): Force loading of lazy-loaded properties.
        def _eval_portgroups(task):
            return task.portgroups

        with task_manager.TaskManager(self.context, 'fake-node-id',
                                      shared=True) as task:
            self.assertRaises(exception.IronicException, _eval_portgroups,
                              task)

        self.assertFalse(reserve_mock.called)
        self.assertFalse(release_mock.called)
        node_get_mock.assert_called_once_with(self.context, 'fake-node-id')
        get_portgroups_mock.assert_called_once_with(self.context, self.node.id)
        self.assertTrue(build_driver_mock.called)

    def test_shared_lock_get_volconn_exception(
            self, get_voltgt_mock, get_volconn_mock, get_portgroups_mock,
            get_ports_mock, build_driver_mock,
            reserve_mock, release_mock, node_get_mock):
        node_get_mock.return_value = self.node
        get_volconn_mock.side_effect = exception.IronicException('foo')

        # Note(arne_wiebalck): Force loading of lazy-loaded properties.
        def _eval_volconn(task):
            return task.volume_connectors

        with task_manager.TaskManager(self.context, 'fake-node-id',
                                      shared=True) as task:
            self.assertRaises(exception.IronicException, _eval_volconn, task)

        self.assertFalse(reserve_mock.called)
        self.assertFalse(release_mock.called)
        node_get_mock.assert_called_once_with(self.context, 'fake-node-id')
        get_volconn_mock.assert_called_once_with(self.context, self.node.id)
        self.assertTrue(build_driver_mock.called)

    def test_shared_lock_get_voltgt_exception(
            self, get_voltgt_mock, get_volconn_mock, get_portgroups_mock,
            get_ports_mock, build_driver_mock,
            reserve_mock, release_mock, node_get_mock):
        node_get_mock.return_value = self.node
        get_voltgt_mock.side_effect = exception.IronicException('foo')

        # Note(arne_wiebalck): Force loading of lazy-loaded properties.
        def _eval_voltgt(task):
            return task.volume_targets

        with task_manager.TaskManager(self.context, 'fake-node-id',
                                      shared=True) as task:
            self.assertRaises(exception.IronicException, _eval_voltgt, task)

        self.assertFalse(reserve_mock.called)
        self.assertFalse(release_mock.called)
        node_get_mock.assert_called_once_with(self.context, 'fake-node-id')
        get_voltgt_mock.assert_called_once_with(self.context, self.node.id)
        self.assertTrue(build_driver_mock.called)

    def test_shared_lock_build_driver_exception(
            self, get_voltgt_mock, get_volconn_mock, get_portgroups_mock,
            get_ports_mock, build_driver_mock,
            reserve_mock, release_mock, node_get_mock):
        node_get_mock.return_value = self.node
        build_driver_mock.side_effect = (
            exception.DriverNotFound(driver_name='foo'))

        self.assertRaises(exception.DriverNotFound,
                          task_manager.TaskManager,
                          self.context,
                          'fake-node-id',
                          shared=True)

        self.assertFalse(reserve_mock.called)
        self.assertFalse(release_mock.called)
        node_get_mock.assert_called_once_with(self.context, 'fake-node-id')
        self.assertFalse(get_ports_mock.called)
        self.assertFalse(get_portgroups_mock.called)
        self.assertFalse(get_voltgt_mock.called)
        self.assertFalse(get_volconn_mock.called)
        build_driver_mock.assert_called_once_with(mock.ANY)

    def test_upgrade_lock(
            self, get_voltgt_mock, get_volconn_mock, get_portgroups_mock,
            get_ports_mock, build_driver_mock,
            reserve_mock, release_mock, node_get_mock):
        node_get_mock.return_value = self.node
        reserve_mock.return_value = self.node
        with task_manager.TaskManager(self.context, 'fake-node-id',
                                      shared=True, purpose='ham') as task:
            self.assertEqual(self.context, task.context)
            self.assertEqual(self.node, task.node)
            self.assertEqual(get_ports_mock.return_value, task.ports)
            self.assertEqual(get_portgroups_mock.return_value, task.portgroups)
            self.assertEqual(get_volconn_mock.return_value,
                             task.volume_connectors)
            self.assertEqual(get_voltgt_mock.return_value, task.volume_targets)
            self.assertEqual(build_driver_mock.return_value, task.driver)
            self.assertTrue(task.shared)
            self.assertFalse(reserve_mock.called)

            task.upgrade_lock()
            self.assertFalse(task.shared)
            self.assertEqual('ham', task._purpose)
            # second upgrade does nothing except changes the purpose
            task.upgrade_lock(purpose='spam')
            self.assertFalse(task.shared)
            self.assertEqual('spam', task._purpose)

            build_driver_mock.assert_called_once_with(mock.ANY)

        # make sure reserve() was called only once
        reserve_mock.assert_called_once_with(self.context, self.host,
                                             'fake-node-id')
        release_mock.assert_called_once_with(self.context, self.host,
                                             self.node.id)
        node_get_mock.assert_called_once_with(self.context, 'fake-node-id')
        get_ports_mock.assert_called_once_with(self.context, self.node.id)
        get_portgroups_mock.assert_called_once_with(self.context, self.node.id)
        get_volconn_mock.assert_called_once_with(self.context, self.node.id)
        get_voltgt_mock.assert_called_once_with(self.context, self.node.id)

    def test_upgrade_lock_refreshes_fsm(self, get_voltgt_mock,
                                        get_volconn_mock, get_portgroups_mock,
                                        get_ports_mock, build_driver_mock,
                                        reserve_mock, release_mock,
                                        node_get_mock):
        reserve_mock.return_value = self.node
        node_get_mock.return_value = self.node
        with task_manager.acquire(self.context, 'fake-node-id',
                                  shared=True) as task1:
            self.assertEqual(states.AVAILABLE, task1.node.provision_state)

            with task_manager.acquire(self.context, 'fake-node-id',
                                      shared=False) as task2:
                # move the node to manageable
                task2.process_event('manage')
                self.assertEqual(states.MANAGEABLE, task1.node.provision_state)

            # now upgrade our shared task and try to go to cleaning
            # this will explode if task1's FSM doesn't get refreshed
            task1.upgrade_lock()
            task1.process_event('provide')
            self.assertEqual(states.CLEANING, task1.node.provision_state)

    @mock.patch.object(task_manager.TaskManager,
                       '_notify_provision_state_change', autospec=True)
    def test_spawn_after(
            self, notify_mock, get_voltgt_mock, get_volconn_mock,
            get_portgroups_mock, get_ports_mock, build_driver_mock,
            reserve_mock, release_mock, node_get_mock):
        spawn_mock = mock.Mock(return_value=self.future_mock)
        task_release_mock = mock.Mock()
        reserve_mock.return_value = self.node

        with task_manager.TaskManager(self.context, 'node-id') as task:
            task.spawn_after(spawn_mock, 1, 2, foo='bar', cat='meow')
            task.release_resources = task_release_mock

        spawn_mock.assert_called_once_with(1, 2, foo='bar', cat='meow')
        self.future_mock.add_done_callback.assert_called_once_with(
            task._thread_release_resources)
        self.assertFalse(self.future_mock.cancel.called)
        # Since we mocked link(), we're testing that __exit__ didn't
        # release resources pending the finishing of the background
        # thread
        self.assertFalse(task_release_mock.called)
        notify_mock.assert_called_once_with(task)

    def test_spawn_after_exception_while_yielded(
            self, get_voltgt_mock, get_volconn_mock, get_portgroups_mock,
            get_ports_mock, build_driver_mock,
            reserve_mock, release_mock, node_get_mock):
        spawn_mock = mock.Mock()
        task_release_mock = mock.Mock()
        reserve_mock.return_value = self.node

        def _test_it():
            with task_manager.TaskManager(self.context, 'node-id') as task:
                task.spawn_after(spawn_mock, 1, 2, foo='bar', cat='meow')
                task.release_resources = task_release_mock
                raise exception.IronicException('foo')

        self.assertRaises(exception.IronicException, _test_it)
        self.assertFalse(spawn_mock.called)
        task_release_mock.assert_called_once_with()

    @mock.patch.object(task_manager.TaskManager,
                       '_notify_provision_state_change', autospec=True)
    def test_spawn_after_spawn_fails(
            self, notify_mock, get_voltgt_mock, get_volconn_mock,
            get_portgroups_mock, get_ports_mock, build_driver_mock,
            reserve_mock, release_mock, node_get_mock):
        spawn_mock = mock.Mock(side_effect=exception.IronicException('foo'))
        task_release_mock = mock.Mock()
        reserve_mock.return_value = self.node

        def _test_it():
            with task_manager.TaskManager(self.context, 'node-id') as task:
                task.spawn_after(spawn_mock, 1, 2, foo='bar', cat='meow')
                task.release_resources = task_release_mock

        self.assertRaises(exception.IronicException, _test_it)

        spawn_mock.assert_called_once_with(1, 2, foo='bar', cat='meow')
        task_release_mock.assert_called_once_with()
        self.assertFalse(notify_mock.called)

    def test_spawn_after_link_fails(
            self, get_voltgt_mock, get_volconn_mock, get_portgroups_mock,
            get_ports_mock, build_driver_mock,
            reserve_mock, release_mock, node_get_mock):
        self.future_mock.add_done_callback.side_effect = (
            exception.IronicException('foo'))
        spawn_mock = mock.Mock(return_value=self.future_mock)
        task_release_mock = mock.Mock()
        thr_release_mock = mock.Mock(spec_set=[])
        reserve_mock.return_value = self.node

        def _test_it():
            with task_manager.TaskManager(self.context, 'node-id') as task:
                task.spawn_after(spawn_mock, 1, 2, foo='bar', cat='meow')
                task._thread_release_resources = thr_release_mock
                task.release_resources = task_release_mock
        self.assertRaises(exception.IronicException, _test_it)

        spawn_mock.assert_called_once_with(1, 2, foo='bar', cat='meow')
        self.future_mock.add_done_callback.assert_called_once_with(
            thr_release_mock)
        self.future_mock.cancel.assert_called_once_with()
        task_release_mock.assert_called_once_with()

    def test_spawn_after_on_error_hook(
            self, get_voltgt_mock, get_volconn_mock, get_portgroups_mock,
            get_ports_mock, build_driver_mock,
            reserve_mock, release_mock, node_get_mock):
        expected_exception = exception.IronicException('foo')
        spawn_mock = mock.Mock(side_effect=expected_exception)
        task_release_mock = mock.Mock()
        on_error_handler = mock.Mock()
        reserve_mock.return_value = self.node

        def _test_it():
            with task_manager.TaskManager(self.context, 'node-id') as task:
                task.set_spawn_error_hook(on_error_handler, 'fake-argument')
                task.spawn_after(spawn_mock, 1, 2, foo='bar', cat='meow')
                task.release_resources = task_release_mock

        self.assertRaises(exception.IronicException, _test_it)

        spawn_mock.assert_called_once_with(1, 2, foo='bar', cat='meow')
        task_release_mock.assert_called_once_with()
        on_error_handler.assert_called_once_with(expected_exception,
                                                 'fake-argument')

    def test_spawn_after_on_error_hook_exception(
            self, get_voltgt_mock, get_volconn_mock, get_portgroups_mock,
            get_ports_mock, build_driver_mock,
            reserve_mock, release_mock, node_get_mock):
        expected_exception = exception.IronicException('foo')
        spawn_mock = mock.Mock(side_effect=expected_exception)
        task_release_mock = mock.Mock()
        # Raise an exception within the on_error handler
        on_error_handler = mock.Mock(side_effect=Exception('unexpected'))
        on_error_handler.__name__ = 'foo_method'
        reserve_mock.return_value = self.node

        def _test_it():
            with task_manager.TaskManager(self.context, 'node-id') as task:
                task.set_spawn_error_hook(on_error_handler, 'fake-argument')
                task.spawn_after(spawn_mock, 1, 2, foo='bar', cat='meow')
                task.release_resources = task_release_mock

        # Make sure the original exception is the one raised
        self.assertRaises(exception.IronicException, _test_it)

        spawn_mock.assert_called_once_with(1, 2, foo='bar', cat='meow')
        task_release_mock.assert_called_once_with()
        on_error_handler.assert_called_once_with(expected_exception,
                                                 'fake-argument')

    @mock.patch.object(states.machine, 'copy')
    def test_init_prepares_fsm(
            self, copy_mock, get_volconn_mock, get_voltgt_mock,
            get_portgroups_mock, get_ports_mock,
            build_driver_mock, reserve_mock, release_mock, node_get_mock):
        m = mock.Mock(spec=fsm.FSM)
        reserve_mock.return_value = self.node
        copy_mock.return_value = m
        t = task_manager.TaskManager('fake', 'fake')
        copy_mock.assert_called_once_with()
        self.assertIs(m, t.fsm)
        m.initialize.assert_called_once_with(
            start_state=self.node.provision_state,
            target_state=self.node.target_provision_state)


class TaskManagerStateModelTestCases(tests_base.TestCase):
    def setUp(self):
        super(TaskManagerStateModelTestCases, self).setUp()
        self.fsm = mock.Mock(spec=fsm.FSM)
        self.node = mock.Mock(spec=objects.Node)
        self.task = mock.Mock(spec=task_manager.TaskManager)
        self.task.fsm = self.fsm
        self.task.node = self.node

    def test_release_clears_resources(self):
        t = self.task
        t.release_resources = task_manager.TaskManager.release_resources
        t.driver = mock.Mock()
        t.ports = mock.Mock()
        t.portgroups = mock.Mock()
        t.volume_connectors = mock.Mock()
        t.volume_targets = mock.Mock()
        t.shared = True
        t._purpose = 'purpose'
        t._debug_timer = mock.Mock()
        t._debug_timer.elapsed.return_value = 3.14

        t.release_resources(t)
        self.assertIsNone(t.node)
        self.assertIsNone(t.driver)
        self.assertIsNone(t.ports)
        self.assertIsNone(t.portgroups)
        self.assertIsNone(t.volume_connectors)
        self.assertIsNone(t.volume_targets)
        self.assertIsNone(t.fsm)

    def test_process_event_fsm_raises(self):
        self.task.process_event = task_manager.TaskManager.process_event
        self.fsm.process_event.side_effect = exception.InvalidState('test')

        self.assertRaises(
            exception.InvalidState,
            self.task.process_event,
            self.task, 'fake')
        self.assertEqual(0, self.task.spawn_after.call_count)
        self.assertFalse(self.task.node.save.called)

    def test_process_event_sets_callback(self):
        cb = mock.Mock()
        arg = mock.Mock()
        kwarg = mock.Mock()
        self.task.process_event = task_manager.TaskManager.process_event
        self.task.process_event(
            self.task, 'fake', callback=cb, call_args=[arg],
            call_kwargs={'mock': kwarg})
        self.fsm.process_event.assert_called_once_with('fake',
                                                       target_state=None)
        self.task.spawn_after.assert_called_with(cb, arg, mock=kwarg)
        self.assertEqual(1, self.task.node.save.call_count)
        self.assertIsNone(self.node.last_error)

    def test_process_event_sets_callback_and_error_handler(self):
        arg = mock.Mock()
        cb = mock.Mock()
        er = mock.Mock()
        kwarg = mock.Mock()
        provision_state = 'provision_state'
        target_provision_state = 'target'
        self.node.provision_state = provision_state
        self.node.target_provision_state = target_provision_state
        self.task.process_event = task_manager.TaskManager.process_event

        self.task.process_event(
            self.task, 'fake', callback=cb, call_args=[arg],
            call_kwargs={'mock': kwarg}, err_handler=er)

        self.task.set_spawn_error_hook.assert_called_once_with(
            er, self.node, provision_state, target_provision_state)
        self.fsm.process_event.assert_called_once_with('fake',
                                                       target_state=None)
        self.task.spawn_after.assert_called_with(cb, arg, mock=kwarg)
        self.assertEqual(1, self.task.node.save.call_count)
        self.assertIsNone(self.node.last_error)
        self.assertNotEqual(provision_state, self.node.provision_state)
        self.assertNotEqual(target_provision_state,
                            self.node.target_provision_state)

    def test_process_event_sets_target_state(self):
        event = 'fake'
        tgt_state = 'target'
        provision_state = 'provision_state'
        target_provision_state = 'target_provision_state'
        self.node.provision_state = provision_state
        self.node.target_provision_state = target_provision_state
        self.task.process_event = task_manager.TaskManager.process_event
        self.task.process_event(self.task, event, target_state=tgt_state)
        self.fsm.process_event.assert_called_once_with(event,
                                                       target_state=tgt_state)
        self.assertEqual(1, self.task.node.save.call_count)
        self.assertNotEqual(provision_state, self.node.provision_state)
        self.assertNotEqual(target_provision_state,
                            self.node.target_provision_state)

    def test_process_event_callback_stable_state(self):
        callback = mock.Mock()
        for state in states.STABLE_STATES:
            self.node.provision_state = state
            self.node.target_provision_state = 'target'
            self.task.process_event = task_manager.TaskManager.process_event
            self.task.process_event(self.task, 'fake', callback=callback)
            # assert the target state is set when callback is passed
            self.assertNotEqual(states.NOSTATE,
                                self.task.node.target_provision_state)

    def test_process_event_no_callback_stable_state(self):
        for state in states.STABLE_STATES:
            self.node.provision_state = state
            self.node.target_provision_state = 'target'
            self.task.process_event = task_manager.TaskManager.process_event
            self.task.process_event(self.task, 'fake')
            # assert the target state was cleared when moving to a
            # stable state
            self.assertEqual(states.NOSTATE,
                             self.task.node.target_provision_state)

    def test_process_event_no_callback_notify(self):
        self.task.process_event = task_manager.TaskManager.process_event
        self.task.process_event(self.task, 'fake')
        self.task._notify_provision_state_change.assert_called_once_with()


@task_manager.require_exclusive_lock
def _req_excl_lock_method(*args, **kwargs):
    return (args, kwargs)


class ExclusiveLockDecoratorTestCase(tests_base.TestCase):
    def setUp(self):
        super(ExclusiveLockDecoratorTestCase, self).setUp()
        self.task = mock.Mock(spec=task_manager.TaskManager)
        self.task.context = self.context
        self.args_task_first = (self.task, 1, 2)
        self.args_task_second = (1, self.task, 2)
        self.kwargs = dict(cat='meow', dog='wuff')

    def test_with_excl_lock_task_first_arg(self):
        self.task.shared = False
        (args, kwargs) = _req_excl_lock_method(*self.args_task_first,
                                               **self.kwargs)
        self.assertEqual(self.args_task_first, args)
        self.assertEqual(self.kwargs, kwargs)

    def test_with_excl_lock_task_second_arg(self):
        self.task.shared = False
        (args, kwargs) = _req_excl_lock_method(*self.args_task_second,
                                               **self.kwargs)
        self.assertEqual(self.args_task_second, args)
        self.assertEqual(self.kwargs, kwargs)

    def test_with_shared_lock_task_first_arg(self):
        self.task.shared = True
        self.assertRaises(exception.ExclusiveLockRequired,
                          _req_excl_lock_method,
                          *self.args_task_first,
                          **self.kwargs)

    def test_with_shared_lock_task_second_arg(self):
        self.task.shared = True
        self.assertRaises(exception.ExclusiveLockRequired,
                          _req_excl_lock_method,
                          *self.args_task_second,
                          **self.kwargs)


class ThreadExceptionTestCase(tests_base.TestCase):
    def setUp(self):
        super(ThreadExceptionTestCase, self).setUp()
        self.node = mock.Mock(spec=objects.Node)
        self.node.last_error = None
        self.task = mock.Mock(spec=task_manager.TaskManager)
        self.task.node = self.node
        self.task._write_exception = task_manager.TaskManager._write_exception
        self.future_mock = mock.Mock(spec_set=['exception'])

        def async_method_foo():
            pass

        self.task._spawn_args = (async_method_foo,)

    def test_set_node_last_error(self):
        self.future_mock.exception.return_value = Exception('fiasco')
        self.task._write_exception(self.task, self.future_mock)
        self.node.save.assert_called_once_with()
        self.assertIn('fiasco', self.node.last_error)
        self.assertIn('async_method_foo', self.node.last_error)

    def test_set_node_last_error_exists(self):
        self.future_mock.exception.return_value = Exception('fiasco')
        self.node.last_error = 'oops'
        self.task._write_exception(self.task, self.future_mock)
        self.assertFalse(self.node.save.called)
        self.assertFalse(self.future_mock.exception.called)
        self.assertEqual('oops', self.node.last_error)

    def test_set_node_last_error_no_error(self):
        self.future_mock.exception.return_value = None
        self.task._write_exception(self.task, self.future_mock)
        self.assertFalse(self.node.save.called)
        self.future_mock.exception.assert_called_once_with()
        self.assertIsNone(self.node.last_error)

    @mock.patch.object(task_manager.LOG, 'exception', spec_set=True,
                       autospec=True)
    def test_set_node_last_error_cancelled(self, log_mock):
        self.future_mock.exception.side_effect = futurist.CancelledError()
        self.task._write_exception(self.task, self.future_mock)
        self.assertFalse(self.node.save.called)
        self.future_mock.exception.assert_called_once_with()
        self.assertIsNone(self.node.last_error)
        self.assertTrue(log_mock.called)


@mock.patch.object(notification_utils, 'emit_provision_set_notification',
                   autospec=True)
class ProvisionNotifyTestCase(tests_base.TestCase):
    def setUp(self):
        super(ProvisionNotifyTestCase, self).setUp()
        self.node = mock.Mock(spec=objects.Node)
        self.task = mock.Mock(spec=task_manager.TaskManager)
        self.task.node = self.node
        notifier = task_manager.TaskManager._notify_provision_state_change
        self.task.notifier = notifier
        self.task._prev_target_provision_state = 'oldtarget'
        self.task._event = 'event'

    def test_notify_no_state_change(self, emit_mock):
        self.task._event = None
        self.task.notifier(self.task)
        self.assertFalse(emit_mock.called)

    def test_notify_error_state(self, emit_mock):
        self.task._event = 'fail'
        self.task._prev_provision_state = 'fake'
        self.task.notifier(self.task)
        emit_mock.assert_called_once_with(self.task,
                                          fields.NotificationLevel.ERROR,
                                          fields.NotificationStatus.ERROR,
                                          'fake', 'oldtarget', 'fail')
        self.assertIsNone(self.task._event)

    def test_notify_unstable_to_unstable(self, emit_mock):
        self.node.provision_state = states.DEPLOYING
        self.task._prev_provision_state = states.DEPLOYWAIT
        self.task.notifier(self.task)
        emit_mock.assert_called_once_with(self.task,
                                          fields.NotificationLevel.INFO,
                                          fields.NotificationStatus.SUCCESS,
                                          states.DEPLOYWAIT,
                                          'oldtarget', 'event')

    def test_notify_stable_to_unstable(self, emit_mock):
        self.node.provision_state = states.DEPLOYING
        self.task._prev_provision_state = states.AVAILABLE
        self.task.notifier(self.task)
        emit_mock.assert_called_once_with(self.task,
                                          fields.NotificationLevel.INFO,
                                          fields.NotificationStatus.START,
                                          states.AVAILABLE,
                                          'oldtarget', 'event')

    def test_notify_unstable_to_stable(self, emit_mock):
        self.node.provision_state = states.ACTIVE
        self.task._prev_provision_state = states.DEPLOYING
        self.task.notifier(self.task)
        emit_mock.assert_called_once_with(self.task,
                                          fields.NotificationLevel.INFO,
                                          fields.NotificationStatus.END,
                                          states.DEPLOYING,
                                          'oldtarget', 'event')

    def test_notify_stable_to_stable(self, emit_mock):
        self.node.provision_state = states.MANAGEABLE
        self.task._prev_provision_state = states.AVAILABLE
        self.task.notifier(self.task)
        emit_mock.assert_called_once_with(self.task,
                                          fields.NotificationLevel.INFO,
                                          fields.NotificationStatus.SUCCESS,
                                          states.AVAILABLE,
                                          'oldtarget', 'event')

    def test_notify_resource_released(self, emit_mock):
        node = mock.Mock(spec=objects.Node)
        node.provision_state = states.DEPLOYING
        node.target_provision_state = states.ACTIVE
        task = mock.Mock(spec=task_manager.TaskManager)
        task._prev_provision_state = states.AVAILABLE
        task._prev_target_provision_state = states.NOSTATE
        task._event = 'event'
        task.node = None
        task._saved_node = node
        notifier = task_manager.TaskManager._notify_provision_state_change
        task.notifier = notifier
        task.notifier(task)
        task_arg = emit_mock.call_args[0][0]
        self.assertEqual(node, task_arg.node)
        self.assertIsNot(task, task_arg)

    def test_notify_only_once(self, emit_mock):
        self.node.provision_state = states.DEPLOYING
        self.task._prev_provision_state = states.AVAILABLE
        self.task.notifier(self.task)
        self.assertIsNone(self.task._event)
        self.task.notifier(self.task)
        self.assertEqual(1, emit_mock.call_count)
        self.assertIsNone(self.task._event)
