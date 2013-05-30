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

"""Tests for :class:`ironic.manager.task_manager`."""

from testtools import matchers

from ironic.common import exception
from ironic.db import api as dbapi
from ironic.manager import task_manager
from ironic.openstack.common import uuidutils
from ironic.tests.db import base
from ironic.tests.db import utils
from ironic.tests.manager import utils as mgr_utils


def create_fake_node(i):
    dbh = dbapi.get_instance()
    node = utils.get_test_node(id=i,
                               uuid=uuidutils.generate_uuid(),
                               control_driver='fake',
                               deploy_driver='fake')
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
        (self.controller, self.deployer) = mgr_utils.get_mocked_node_manager()

        self.uuids = [create_fake_node(i) for i in xrange(1, 6)]
        self.uuids.sort()

    def test_get_one_node(self):
        uuids = [self.uuids[0]]

        self.config(host='test-host')

        with task_manager.acquire(uuids) as task:
            node = task.resources[0].node
            self.assertEqual(uuids[0], node.uuid)
            self.assertEqual('test-host', node.reservation)

    def test_get_many_nodes(self):
        uuids = self.uuids[1:3]

        self.config(host='test-host')

        with task_manager.acquire(uuids) as task:
            self.assertThat(task, ContainsUUIDs(uuids))
            for node in [r.node for r in task.resources]:
                self.assertEqual('test-host', node.reservation)

    def test_get_nodes_nested(self):
        uuids = self.uuids[0:2]
        more_uuids = self.uuids[3:4]

        with task_manager.acquire(uuids) as task:
            self.assertThat(task, ContainsUUIDs(uuids))
            with task_manager.acquire(more_uuids) as another_task:
                self.assertThat(another_task, ContainsUUIDs(more_uuids))

    def test_get_locked_node(self):
        uuids = self.uuids[0:2]

        def _lock_again(u):
            with task_manager.acquire(u):
                raise exception.IronicException("Acquired lock twice.")

        with task_manager.acquire(uuids) as task:
            self.assertThat(task, ContainsUUIDs(uuids))
            self.assertRaises(exception.NodeLocked,
                              _lock_again,
                              uuids)

    def test_get_shared_lock(self):
        uuids = self.uuids[0:2]

        # confirm we can elevate from shared -> exclusive
        with task_manager.acquire(uuids, shared=True) as task:
            self.assertThat(task, ContainsUUIDs(uuids))
            with task_manager.acquire(uuids, shared=False) as inner_task:
                self.assertThat(inner_task, ContainsUUIDs(uuids))

        # confirm someone else can still get a shared lock
        with task_manager.acquire(uuids, shared=False) as task:
            self.assertThat(task, ContainsUUIDs(uuids))
            with task_manager.acquire(uuids, shared=True) as inner_task:
                self.assertThat(inner_task, ContainsUUIDs(uuids))


class ExclusiveLockDecoratorTestCase(base.DbTestCase):

    def setUp(self):
        super(ExclusiveLockDecoratorTestCase, self).setUp()
        self.dbapi = dbapi.get_instance()
        (self.controller, self.deployer) = mgr_utils.get_mocked_node_manager()
        self.uuids = [create_fake_node(123)]

    def test_require_exclusive_lock(self):
        @task_manager.require_exclusive_lock
        def do_state_change(task):
            for r in task.resources:
                task.dbapi.update_node(r.node.uuid,
                                       {'task_state': 'test-state'})

        with task_manager.acquire(self.uuids, shared=True) as task:
            self.assertRaises(exception.ExclusiveLockRequired,
                              do_state_change,
                              task)

        with task_manager.acquire(self.uuids, shared=False) as task:
            do_state_change(task)

        for uuid in self.uuids:
            res = self.dbapi.get_node(uuid)
            self.assertEqual('test-state', res.task_state)

    @task_manager.require_exclusive_lock
    def _do_state_change(self, task):
        for r in task.resources:
            task.dbapi.update_node(r.node.uuid,
                                   {'task_state': 'test-state'})

    def test_require_exclusive_lock_on_object(self):
        with task_manager.acquire(self.uuids, shared=True) as task:
            self.assertRaises(exception.ExclusiveLockRequired,
                              self._do_state_change,
                              task)

        with task_manager.acquire(self.uuids, shared=False) as task:
            self._do_state_change(task)

        for uuid in self.uuids:
            res = self.dbapi.get_node(uuid)
            self.assertEqual('test-state', res.task_state)
