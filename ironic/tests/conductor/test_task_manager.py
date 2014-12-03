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

import eventlet
from eventlet import greenpool
import mock

from ironic.common import driver_factory
from ironic.common import exception
from ironic.common import utils
from ironic.conductor import task_manager
from ironic import objects
from ironic.tests import base as tests_base
from ironic.tests.db import base as tests_db_base
from ironic.tests.objects import utils as obj_utils


@mock.patch.object(objects.Node, 'get')
@mock.patch.object(objects.Node, 'release')
@mock.patch.object(objects.Node, 'reserve')
@mock.patch.object(driver_factory, 'get_driver')
@mock.patch.object(objects.Port, 'list_by_node_id')
class TaskManagerTestCase(tests_db_base.DbTestCase):
    def setUp(self):
        super(TaskManagerTestCase, self).setUp()
        self.host = 'test-host'
        self.config(host=self.host)
        self.config(node_locked_retry_attempts=1, group='conductor')
        self.config(node_locked_retry_interval=0, group='conductor')
        self.node = obj_utils.create_test_node(self.context)

    def test_excl_lock(self, get_ports_mock, get_driver_mock,
                       reserve_mock, release_mock, node_get_mock):
        reserve_mock.return_value = self.node
        with task_manager.TaskManager(self.context, 'fake-node-id') as task:
            self.assertEqual(self.context, task.context)
            self.assertEqual(self.node, task.node)
            self.assertEqual(get_ports_mock.return_value, task.ports)
            self.assertEqual(get_driver_mock.return_value, task.driver)
            self.assertFalse(task.shared)

        reserve_mock.assert_called_once_with(self.context, self.host,
                                             'fake-node-id')
        get_ports_mock.assert_called_once_with(self.context, self.node.id)
        get_driver_mock.assert_called_once_with(self.node.driver)
        release_mock.assert_called_once_with(self.context, self.host,
                                             self.node.id)
        self.assertFalse(node_get_mock.called)

    def test_excl_lock_with_driver(self, get_ports_mock, get_driver_mock,
                                   reserve_mock, release_mock,
                                   node_get_mock):
        reserve_mock.return_value = self.node
        with task_manager.TaskManager(self.context, 'fake-node-id',
                                      driver_name='fake-driver') as task:
            self.assertEqual(self.context, task.context)
            self.assertEqual(self.node, task.node)
            self.assertEqual(get_ports_mock.return_value, task.ports)
            self.assertEqual(get_driver_mock.return_value, task.driver)
            self.assertFalse(task.shared)

        reserve_mock.assert_called_once_with(self.context, self.host,
                                             'fake-node-id')
        get_ports_mock.assert_called_once_with(self.context, self.node.id)
        get_driver_mock.assert_called_once_with('fake-driver')
        release_mock.assert_called_once_with(self.context, self.host,
                                             self.node.id)
        self.assertFalse(node_get_mock.called)

    def test_excl_nested_acquire(self, get_ports_mock, get_driver_mock,
                                 reserve_mock, release_mock,
                                 node_get_mock):
        node2 = obj_utils.create_test_node(self.context,
                                           uuid=utils.generate_uuid(),
                                           driver='fake')

        reserve_mock.return_value = self.node
        get_ports_mock.return_value = mock.sentinel.ports1
        get_driver_mock.return_value = mock.sentinel.driver1

        with task_manager.TaskManager(self.context, 'node-id1') as task:
            reserve_mock.return_value = node2
            get_ports_mock.return_value = mock.sentinel.ports2
            get_driver_mock.return_value = mock.sentinel.driver2
            with task_manager.TaskManager(self.context, 'node-id2') as task2:
                self.assertEqual(self.context, task.context)
                self.assertEqual(self.node, task.node)
                self.assertEqual(mock.sentinel.ports1, task.ports)
                self.assertEqual(mock.sentinel.driver1, task.driver)
                self.assertFalse(task.shared)
                self.assertEqual(self.context, task2.context)
                self.assertEqual(node2, task2.node)
                self.assertEqual(mock.sentinel.ports2, task2.ports)
                self.assertEqual(mock.sentinel.driver2, task2.driver)
                self.assertFalse(task2.shared)

        self.assertEqual([mock.call(self.context, self.host, 'node-id1'),
                          mock.call(self.context, self.host, 'node-id2')],
                         reserve_mock.call_args_list)
        self.assertEqual([mock.call(self.context, self.node.id),
                          mock.call(self.context, node2.id)],
                         get_ports_mock.call_args_list)
        self.assertEqual([mock.call(self.node.driver),
                          mock.call(node2.driver)],
                         get_driver_mock.call_args_list)
        # release should be in reverse order
        self.assertEqual([mock.call(self.context, self.host, node2.id),
                          mock.call(self.context, self.host, self.node.id)],
                         release_mock.call_args_list)
        self.assertFalse(node_get_mock.called)

    def test_excl_lock_exception_then_lock(self, get_ports_mock,
                                           get_driver_mock, reserve_mock,
                                           release_mock, node_get_mock):
        retry_attempts = 3
        self.config(node_locked_retry_attempts=retry_attempts,
                    group='conductor')

        # Fail on the first lock attempt, succeed on the second.
        reserve_mock.side_effect = [exception.NodeLocked(node='foo',
                                                         host='foo'),
                                    self.node]

        with task_manager.TaskManager(self.context, 'fake-node-id') as task:
            self.assertFalse(task.shared)

        reserve_mock.assert_called(self.context, self.host, 'fake-node-id')
        self.assertEqual(2, reserve_mock.call_count)

    def test_excl_lock_reserve_exception(self, get_ports_mock,
                                         get_driver_mock, reserve_mock,
                                         release_mock, node_get_mock):
        retry_attempts = 3
        self.config(node_locked_retry_attempts=retry_attempts,
                    group='conductor')
        reserve_mock.side_effect = exception.NodeLocked(node='foo',
                                                        host='foo')

        self.assertRaises(exception.NodeLocked,
                          task_manager.TaskManager,
                          self.context,
                          'fake-node-id')

        reserve_mock.assert_called_with(self.context, self.host,
                                        'fake-node-id')
        self.assertEqual(retry_attempts, reserve_mock.call_count)
        self.assertFalse(get_ports_mock.called)
        self.assertFalse(get_driver_mock.called)
        self.assertFalse(release_mock.called)
        self.assertFalse(node_get_mock.called)

    def test_excl_lock_get_ports_exception(self, get_ports_mock,
                                           get_driver_mock, reserve_mock,
                                           release_mock, node_get_mock):
        reserve_mock.return_value = self.node
        get_ports_mock.side_effect = exception.IronicException('foo')

        self.assertRaises(exception.IronicException,
                          task_manager.TaskManager,
                          self.context,
                          'fake-node-id')

        reserve_mock.assert_called_once_with(self.context, self.host,
                                             'fake-node-id')
        get_ports_mock.assert_called_once_with(self.context, self.node.id)
        self.assertFalse(get_driver_mock.called)
        release_mock.assert_called_once_with(self.context, self.host,
                                             self.node.id)
        self.assertFalse(node_get_mock.called)

    def test_excl_lock_get_driver_exception(self, get_ports_mock,
                                            get_driver_mock, reserve_mock,
                                            release_mock, node_get_mock):
        reserve_mock.return_value = self.node
        get_driver_mock.side_effect = exception.DriverNotFound(
                driver_name='foo')

        self.assertRaises(exception.DriverNotFound,
                          task_manager.TaskManager,
                          self.context,
                          'fake-node-id')

        reserve_mock.assert_called_once_with(self.context, self.host,
                                             'fake-node-id')
        get_ports_mock.assert_called_once_with(self.context, self.node.id)
        get_driver_mock.assert_called_once_with(self.node.driver)
        release_mock.assert_called_once_with(self.context, self.host,
                                             self.node.id)
        self.assertFalse(node_get_mock.called)

    def test_shared_lock(self, get_ports_mock, get_driver_mock,
                         reserve_mock, release_mock, node_get_mock):
        node_get_mock.return_value = self.node
        with task_manager.TaskManager(self.context, 'fake-node-id',
                                      shared=True) as task:
            self.assertEqual(self.context, task.context)
            self.assertEqual(self.node, task.node)
            self.assertEqual(get_ports_mock.return_value, task.ports)
            self.assertEqual(get_driver_mock.return_value, task.driver)
            self.assertTrue(task.shared)

        self.assertFalse(reserve_mock.called)
        self.assertFalse(release_mock.called)
        node_get_mock.assert_called_once_with(self.context, 'fake-node-id')
        get_ports_mock.assert_called_once_with(self.context, self.node.id)
        get_driver_mock.assert_called_once_with(self.node.driver)

    def test_shared_lock_with_driver(self, get_ports_mock, get_driver_mock,
                                     reserve_mock, release_mock,
                                     node_get_mock):
        node_get_mock.return_value = self.node
        with task_manager.TaskManager(self.context,
                                      'fake-node-id',
                                      shared=True,
                                      driver_name='fake-driver') as task:
            self.assertEqual(self.context, task.context)
            self.assertEqual(self.node, task.node)
            self.assertEqual(get_ports_mock.return_value, task.ports)
            self.assertEqual(get_driver_mock.return_value, task.driver)
            self.assertTrue(task.shared)

        self.assertFalse(reserve_mock.called)
        self.assertFalse(release_mock.called)
        node_get_mock.assert_called_once_with(self.context, 'fake-node-id')
        get_ports_mock.assert_called_once_with(self.context, self.node.id)
        get_driver_mock.assert_called_once_with('fake-driver')

    def test_shared_lock_node_get_exception(self, get_ports_mock,
                                            get_driver_mock, reserve_mock,
                                            release_mock, node_get_mock):
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
        self.assertFalse(get_driver_mock.called)

    def test_shared_lock_get_ports_exception(self, get_ports_mock,
                                             get_driver_mock, reserve_mock,
                                             release_mock, node_get_mock):
        node_get_mock.return_value = self.node
        get_ports_mock.side_effect = exception.IronicException('foo')

        self.assertRaises(exception.IronicException,
                          task_manager.TaskManager,
                          self.context,
                          'fake-node-id',
                          shared=True)

        self.assertFalse(reserve_mock.called)
        self.assertFalse(release_mock.called)
        node_get_mock.assert_called_once_with(self.context, 'fake-node-id')
        get_ports_mock.assert_called_once_with(self.context, self.node.id)
        self.assertFalse(get_driver_mock.called)

    def test_shared_lock_get_driver_exception(self, get_ports_mock,
                                              get_driver_mock, reserve_mock,
                                              release_mock, node_get_mock):
        node_get_mock.return_value = self.node
        get_driver_mock.side_effect = exception.DriverNotFound(
                driver_name='foo')

        self.assertRaises(exception.DriverNotFound,
                          task_manager.TaskManager,
                          self.context,
                          'fake-node-id',
                          shared=True)

        self.assertFalse(reserve_mock.called)
        self.assertFalse(release_mock.called)
        node_get_mock.assert_called_once_with(self.context, 'fake-node-id')
        get_ports_mock.assert_called_once_with(self.context, self.node.id)
        get_driver_mock.assert_called_once_with(self.node.driver)

    def test_spawn_after(self, get_ports_mock, get_driver_mock,
                         reserve_mock, release_mock, node_get_mock):
        thread_mock = mock.Mock(spec_set=['link', 'cancel'])
        spawn_mock = mock.Mock(return_value=thread_mock)
        task_release_mock = mock.Mock()
        reserve_mock.return_value = self.node

        with task_manager.TaskManager(self.context, 'node-id') as task:
            task.spawn_after(spawn_mock, 1, 2, foo='bar', cat='meow')
            task.release_resources = task_release_mock

        spawn_mock.assert_called_once_with(1, 2, foo='bar', cat='meow')
        thread_mock.link.assert_called_once_with(
                task._thread_release_resources)
        self.assertFalse(thread_mock.cancel.called)
        # Since we mocked link(), we're testing that __exit__ didn't
        # release resources pending the finishing of the background
        # thread
        self.assertFalse(task_release_mock.called)

    def test_spawn_after_exception_while_yielded(self, get_ports_mock,
                                                 get_driver_mock,
                                                 reserve_mock,
                                                 release_mock,
                                                 node_get_mock):
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

    def test_spawn_after_spawn_fails(self, get_ports_mock, get_driver_mock,
                                     reserve_mock, release_mock,
                                     node_get_mock):
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

    def test_spawn_after_link_fails(self, get_ports_mock, get_driver_mock,
                                    reserve_mock, release_mock,
                                    node_get_mock):
        thread_mock = mock.Mock(spec_set=['link', 'cancel'])
        thread_mock.link.side_effect = exception.IronicException('foo')
        spawn_mock = mock.Mock(return_value=thread_mock)
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
        thread_mock.link.assert_called_once_with(thr_release_mock)
        thread_mock.cancel.assert_called_once_with()
        task_release_mock.assert_called_once_with()

    def test_spawn_after_on_error_hook(self, get_ports_mock, get_driver_mock,
                                       reserve_mock, release_mock,
                                       node_get_mock):
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

    def test_spawn_after_on_error_hook_exception(self, get_ports_mock,
                                                 get_driver_mock, reserve_mock,
                                                 release_mock, node_get_mock):
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


@task_manager.require_exclusive_lock
def _req_excl_lock_method(*args, **kwargs):
    return (args, kwargs)


class ExclusiveLockDecoratorTestCase(tests_base.TestCase):
    def setUp(self):
        super(ExclusiveLockDecoratorTestCase, self).setUp()
        self.task = mock.Mock(spec=task_manager.TaskManager)
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


class TaskManagerGreenThreadTestCase(tests_base.TestCase):
    """Class to assert our assumptions about greenthread behavior."""
    def test_gt_link_callback_added_during_execution(self):
        pool = greenpool.GreenPool()
        q1 = eventlet.Queue()
        q2 = eventlet.Queue()

        def func():
            q1.put(None)
            q2.get()

        link_callback = mock.Mock()

        thread = pool.spawn(func)
        q1.get()
        thread.link(link_callback)
        q2.put(None)
        pool.waitall()
        link_callback.assert_called_once_with(thread)

    def test_gt_link_callback_added_after_execution(self):
        pool = greenpool.GreenPool()
        link_callback = mock.Mock()

        thread = pool.spawn(lambda: None)
        pool.waitall()
        thread.link(link_callback)
        link_callback.assert_called_once_with(thread)

    def test_gt_link_callback_exception_inside_thread(self):
        pool = greenpool.GreenPool()
        q1 = eventlet.Queue()
        q2 = eventlet.Queue()

        def func():
            q1.put(None)
            q2.get()
            raise Exception()

        link_callback = mock.Mock()

        thread = pool.spawn(func)
        q1.get()
        thread.link(link_callback)
        q2.put(None)
        pool.waitall()
        link_callback.assert_called_once_with(thread)

    def test_gt_link_callback_added_after_exception_inside_thread(self):
        pool = greenpool.GreenPool()

        def func():
            raise Exception()

        link_callback = mock.Mock()

        thread = pool.spawn(func)
        pool.waitall()
        thread.link(link_callback)

        link_callback.assert_called_once_with(thread)

    def test_gt_cancel_doesnt_run_thread(self):
        pool = greenpool.GreenPool()
        func = mock.Mock()
        thread = pool.spawn(func)
        thread.link(lambda t: None)
        thread.cancel()
        pool.waitall()
        self.assertFalse(func.called)
