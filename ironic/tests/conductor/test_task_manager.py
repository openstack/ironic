# vim: tabstop=4 shiftwidth=4 softtabstop=4
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

from ironic.common import exception
from ironic.common import utils as ironic_utils
from ironic.conductor import task_manager
from ironic.db import api as dbapi
from ironic.openstack.common import context

from ironic.tests.conductor import utils as mgr_utils
from ironic.tests.db import base
from ironic.tests.db import utils


def create_fake_node(i):
    dbh = dbapi.get_instance()
    node = utils.get_test_node(id=i,
                               uuid=ironic_utils.generate_uuid())
    dbh.create_node(node)
    return node['uuid']


def ContainsUUIDs(uuids):
    def _task_uuids(task):
        return [r.node.uuid for r in task.resources]
    return matchers.AfterPreprocessing(_task_uuids,
                              matchers.Equals(uuids))


class TaskManagerTestCase(base.DbTestCase):

    def setUp(self):
        super(TaskManagerTestCase, self).setUp()
        self.dbapi = dbapi.get_instance()
        self.context = context.get_admin_context()
        self.driver = mgr_utils.get_mocked_node_manager()

        self.uuids = [create_fake_node(i) for i in range(1, 6)]
        self.uuids.sort()

    def test_get_one_node(self):
        uuids = [self.uuids[0]]

        self.config(host='test-host')

        with task_manager.acquire(self.context, uuids) as task:
            node = task.resources[0].node
            self.assertEqual(uuids[0], node.uuid)
            self.assertEqual('test-host', node.reservation)

    def test_get_many_nodes(self):
        uuids = self.uuids[1:3]

        self.config(host='test-host')

        with task_manager.acquire(self.context, uuids) as task:
            self.assertThat(task, ContainsUUIDs(uuids))
            for node in [r.node for r in task.resources]:
                self.assertEqual('test-host', node.reservation)

    def test_get_nodes_nested(self):
        uuids = self.uuids[0:2]
        more_uuids = self.uuids[3:4]

        with task_manager.acquire(self.context, uuids) as task:
            self.assertThat(task, ContainsUUIDs(uuids))
            with task_manager.acquire(self.context,
                                      more_uuids) as another_task:
                self.assertThat(another_task, ContainsUUIDs(more_uuids))

    def test_get_locked_node(self):
        uuids = self.uuids[0:2]

        def _lock_again(u):
            with task_manager.acquire(self.context, u):
                raise exception.IronicException("Acquired lock twice.")

        with task_manager.acquire(self.context, uuids) as task:
            self.assertThat(task, ContainsUUIDs(uuids))
            self.assertRaises(exception.NodeLocked,
                              _lock_again,
                              uuids)

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


class ExclusiveLockDecoratorTestCase(base.DbTestCase):

    def setUp(self):
        super(ExclusiveLockDecoratorTestCase, self).setUp()
        self.dbapi = dbapi.get_instance()
        self.context = context.get_admin_context()
        self.driver = mgr_utils.get_mocked_node_manager()
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
            res = self.dbapi.get_node(uuid)
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
            res = self.dbapi.get_node(uuid)
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
