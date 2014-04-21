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

from testtools import matchers

import eventlet
from eventlet import greenpool
import mock

from ironic.common import driver_factory
from ironic.common import exception
from ironic.common import utils as ironic_utils
from ironic.conductor import task_manager
from ironic.db import api as dbapi
from ironic import objects
from ironic.openstack.common import context

from ironic.tests import base as tests_base
from ironic.tests.conductor import utils as mgr_utils
from ironic.tests.db import base as db_base
from ironic.tests.db import utils


def create_fake_node(i):
    dbh = dbapi.get_instance()
    node = utils.get_test_node(id=i,
                               uuid=ironic_utils.generate_uuid())
    dbh.create_node(node)
    return node['uuid']


def ContainsUUIDs(uuids):
    def _task_uuids(task):
        return sorted([r.node.uuid for r in task.resources])

    return matchers.AfterPreprocessing(
            _task_uuids, matchers.Equals(uuids))


class TaskManagerSetup(db_base.DbTestCase):

    def setUp(self):
        super(TaskManagerSetup, self).setUp()
        self.dbapi = dbapi.get_instance()
        self.context = context.get_admin_context()
        mgr_utils.mock_the_extension_manager()
        self.driver = driver_factory.get_driver("fake")
        self.config(host='test-host')


class TaskManagerTestCase(TaskManagerSetup):

    def setUp(self):
        super(TaskManagerTestCase, self).setUp()
        self.uuids = [create_fake_node(i) for i in range(1, 6)]
        self.uuids.sort()

    def test_task_manager_gets_node(self):
        node_uuid = self.uuids[0]
        task = task_manager.TaskManager(self.context, node_uuid)
        self.assertEqual(node_uuid, task.node.uuid)

    def test_task_manager_updates_db(self):
        node_uuid = self.uuids[0]
        node = objects.Node.get_by_uuid(self.context, node_uuid)
        self.assertIsNone(node.reservation)

        with task_manager.acquire(self.context, node_uuid) as task:
            self.assertEqual(node.uuid, task.node.uuid)
            node.refresh(self.context)
            self.assertEqual('test-host', node.reservation)

        node.refresh(self.context)
        self.assertIsNone(node.reservation)

    def test_get_many_nodes(self):
        uuids = self.uuids[1:3]

        with task_manager.acquire(self.context, uuids) as task:
            self.assertThat(task, ContainsUUIDs(uuids))
            for node in [r.node for r in task.resources]:
                self.assertEqual('test-host', node.reservation)

        # Ensure all reservations are cleared
        for uuid in self.uuids:
            node = objects.Node.get_by_uuid(self.context, uuid)
            self.assertIsNone(node.reservation)

    def test_get_nodes_nested(self):
        uuids = self.uuids[0:2]
        more_uuids = self.uuids[3:4]

        with task_manager.acquire(self.context, uuids) as task:
            self.assertThat(task, ContainsUUIDs(uuids))
            with task_manager.acquire(self.context,
                                      more_uuids) as another_task:
                self.assertThat(another_task, ContainsUUIDs(more_uuids))

    def test_get_shared_lock(self):
        uuids = self.uuids[0:2]

        # confirm we can elevate from shared -> exclusive
        with task_manager.acquire(self.context, uuids, shared=True) as task:
            self.assertThat(task, ContainsUUIDs(uuids))
            with task_manager.acquire(self.context, uuids,
                                      shared=False) as inner_task:
                self.assertThat(inner_task, ContainsUUIDs(uuids))

        # confirm someone else can still get a shared lock
        with task_manager.acquire(self.context, uuids, shared=False) as task:
            self.assertThat(task, ContainsUUIDs(uuids))
            with task_manager.acquire(self.context, uuids,
                                      shared=True) as inner_task:
                self.assertThat(inner_task, ContainsUUIDs(uuids))

    def test_get_one_node_already_locked(self):
        node_uuid = self.uuids[0]
        task_manager.TaskManager(self.context, node_uuid)

        # Check that db node reservation is still set
        # if another TaskManager attempts to acquire the same node
        self.assertRaises(exception.NodeLocked,
                          task_manager.TaskManager,
                          self.context, node_uuid)
        node = objects.Node.get_by_uuid(self.context, node_uuid)
        self.assertEqual('test-host', node.reservation)

    def test_get_many_nodes_some_already_locked(self):
        unlocked_node_uuids = self.uuids[0:2] + self.uuids[3:5]
        locked_node_uuid = self.uuids[2]
        task_manager.TaskManager(self.context, locked_node_uuid)

        # Check that none of the other nodes are reserved
        # and the one which we first locked has not been unlocked
        self.assertRaises(exception.NodeLocked,
                          task_manager.TaskManager,
                          self.context,
                          self.uuids)
        node = objects.Node.get_by_uuid(self.context, locked_node_uuid)
        self.assertEqual('test-host', node.reservation)
        for uuid in unlocked_node_uuids:
            node = objects.Node.get_by_uuid(self.context, uuid)
            self.assertIsNone(node.reservation)

    def test_get_one_node_driver_load_exception(self):
        node_uuid = self.uuids[0]
        self.assertRaises(exception.DriverNotFound,
                          task_manager.TaskManager,
                          self.context, node_uuid,
                          driver_name='no-such-driver')

        # Check that db node reservation is not set.
        node = objects.Node.get_by_uuid(self.context, node_uuid)
        self.assertIsNone(node.reservation)

    @mock.patch.object(driver_factory, 'get_driver')
    @mock.patch.object(dbapi.IMPL, 'get_ports_by_node_id')
    @mock.patch.object(dbapi.IMPL, 'reserve_nodes')
    def test_spawn_after(self, reserve_mock, get_ports_mock,
                         get_driver_mock):
        thread_mock = mock.Mock(spec_set=['link', 'cancel'])
        spawn_mock = mock.Mock(return_value=thread_mock)
        release_mock = mock.Mock()

        with task_manager.TaskManager(self.context, 'node-id') as task:
            task.spawn_after(spawn_mock, 1, 2, foo='bar', cat='meow')
            task.release_resources = release_mock

        spawn_mock.assert_called_once_with(1, 2, foo='bar', cat='meow')
        thread_mock.link.assert_called_once_with(
                task._thread_release_resources)
        self.assertFalse(thread_mock.cancel.called)
        # Since we mocked link(), we're testing that __exit__ didn't
        # release resources pending the finishing of the background
        # thread
        self.assertFalse(release_mock.called)

    @mock.patch.object(driver_factory, 'get_driver')
    @mock.patch.object(dbapi.IMPL, 'get_ports_by_node_id')
    @mock.patch.object(dbapi.IMPL, 'reserve_nodes')
    def test_spawn_after_exception_while_yielded(self, reserve_mock,
                                                 get_ports_mock,
                                                 get_driver_mock):
        spawn_mock = mock.Mock()
        release_mock = mock.Mock()

        def _test_it():
            with task_manager.TaskManager(self.context, 'node-id') as task:
                task.spawn_after(spawn_mock, 1, 2, foo='bar', cat='meow')
                task.release_resources = release_mock
                raise exception.IronicException('foo')

        self.assertRaises(exception.IronicException, _test_it)
        self.assertFalse(spawn_mock.called)
        release_mock.assert_called_once_with()

    @mock.patch.object(driver_factory, 'get_driver')
    @mock.patch.object(dbapi.IMPL, 'get_ports_by_node_id')
    @mock.patch.object(dbapi.IMPL, 'reserve_nodes')
    def test_spawn_after_spawn_fails(self, reserve_mock, get_ports_mock,
                                     get_driver_mock):
        spawn_mock = mock.Mock(side_effect=exception.IronicException('foo'))
        release_mock = mock.Mock()

        def _test_it():
            with task_manager.TaskManager(self.context, 'node-id') as task:
                task.spawn_after(spawn_mock, 1, 2, foo='bar', cat='meow')
                task.release_resources = release_mock

        self.assertRaises(exception.IronicException, _test_it)

        spawn_mock.assert_called_once_with(1, 2, foo='bar', cat='meow')
        release_mock.assert_called_once_with()

    @mock.patch.object(driver_factory, 'get_driver')
    @mock.patch.object(dbapi.IMPL, 'get_ports_by_node_id')
    @mock.patch.object(dbapi.IMPL, 'reserve_nodes')
    def test_spawn_after_link_fails(self, reserve_mock, get_ports_mock,
                                     get_driver_mock):
        thread_mock = mock.Mock(spec_set=['link', 'cancel'])
        thread_mock.link.side_effect = exception.IronicException('foo')
        spawn_mock = mock.Mock(return_value=thread_mock)
        release_mock = mock.Mock()
        thr_release_mock = mock.Mock(spec_set=[])

        def _test_it():
            with task_manager.TaskManager(self.context, 'node-id') as task:
                task.spawn_after(spawn_mock, 1, 2, foo='bar', cat='meow')
                task._thread_release_resources = thr_release_mock
                task.release_resources = release_mock

        self.assertRaises(exception.IronicException, _test_it)

        spawn_mock.assert_called_once_with(1, 2, foo='bar', cat='meow')
        thread_mock.link.assert_called_once_with(thr_release_mock)
        thread_mock.cancel.assert_called_once_with()
        release_mock.assert_called_once_with()


class ExclusiveLockDecoratorTestCase(TaskManagerSetup):

    def setUp(self):
        super(ExclusiveLockDecoratorTestCase, self).setUp()
        self.uuids = [create_fake_node(123)]

    def test_require_exclusive_lock(self):
        @task_manager.require_exclusive_lock
        def do_state_change(task):
            for r in task.resources:
                task.dbapi.update_node(r.node.uuid,
                                       {'power_state': 'test-state'})

        with task_manager.acquire(self.context, self.uuids,
                                  shared=True) as task:
            self.assertRaises(exception.ExclusiveLockRequired,
                              do_state_change,
                              task)

        with task_manager.acquire(self.context, self.uuids,
                                  shared=False) as task:
            do_state_change(task)

        for uuid in self.uuids:
            res = objects.Node.get_by_uuid(self.context, uuid)
            self.assertEqual('test-state', res.power_state)

    @task_manager.require_exclusive_lock
    def _do_state_change(self, task):
        for r in task.resources:
            task.dbapi.update_node(r.node.uuid,
                                   {'power_state': 'test-state'})

    def test_require_exclusive_lock_on_object(self):
        with task_manager.acquire(self.context, self.uuids,
                                  shared=True) as task:
            self.assertRaises(exception.ExclusiveLockRequired,
                              self._do_state_change,
                              task)

        with task_manager.acquire(self.context, self.uuids,
                                  shared=False) as task:
            self._do_state_change(task)

        for uuid in self.uuids:
            res = objects.Node.get_by_uuid(self.context, uuid)
            self.assertEqual('test-state', res.power_state)

    def test_one_node_per_task_properties(self):
        with task_manager.acquire(self.context, self.uuids) as task:
            self.assertEqual(task.node, task.resources[0].node)
            self.assertEqual(task.driver, task.resources[0].driver)
            self.assertEqual(task.node_manager, task.resources[0])

    def test_one_node_per_task_properties_fail(self):
        self.uuids.append(create_fake_node(456))
        with task_manager.acquire(self.context, self.uuids) as task:
            def get_node():
                return task.node

            def get_driver():
                return task.driver

            def get_node_manager():
                return task.node_manager

            self.assertRaises(AttributeError, get_node)
            self.assertRaises(AttributeError, get_driver)
            self.assertRaises(AttributeError, get_node_manager)


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
