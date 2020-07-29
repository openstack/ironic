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

"""Test utils for Ironic Managers."""

from unittest import mock

from futurist import periodics
from oslo_utils import strutils
from oslo_utils import uuidutils

from ironic.common import exception
from ironic.common import states
from ironic.conductor import manager
from ironic import objects


class CommonMixIn(object):
    @staticmethod
    def _create_node(**kwargs):
        attrs = {'id': 1,
                 'uuid': uuidutils.generate_uuid(),
                 'power_state': states.POWER_OFF,
                 'target_power_state': None,
                 'maintenance': False,
                 'reservation': None}
        attrs.update(kwargs)
        node = mock.Mock(spec_set=objects.Node)
        for attr in attrs:
            setattr(node, attr, attrs[attr])
        return node

    def _create_task(self, node=None, node_attrs=None):
        if node_attrs is None:
            node_attrs = {}
        if node is None:
            node = self._create_node(**node_attrs)
        task = mock.Mock(spec_set=['node', 'release_resources',
                                   'spawn_after', 'process_event', 'driver'])
        task.node = node
        return task

    def _get_nodeinfo_list_response(self, nodes=None):
        if nodes is None:
            nodes = [self.node]
        elif not isinstance(nodes, (list, tuple)):
            nodes = [nodes]
        return [tuple(getattr(n, c) for c in self.columns) for n in nodes]

    def _get_acquire_side_effect(self, task_infos):
        """Helper method to generate a task_manager.acquire() side effect.

        This accepts a list of information about task mocks to return.
        task_infos can be a single entity or a list.

        Each task_info can be a single entity, the task to return, or it
        can be a tuple of (task, exception_to_raise_on_exit). 'task' can
        be an exception to raise on __enter__.

        Examples: _get_acquire_side_effect(self, task): Yield task
                  _get_acquire_side_effect(self, [task, enter_exception(),
                                                  (task2, exit_exception())])
                       Yield task on first call to acquire()
                       raise enter_exception() in __enter__ on 2nd call to
                           acquire()
                       Yield task2 on 3rd call to acquire(), but raise
                           exit_exception() on __exit__()
        """
        tasks = []
        exit_exceptions = []
        if not isinstance(task_infos, list):
            task_infos = [task_infos]
        for task_info in task_infos:
            if isinstance(task_info, tuple):
                task, exc = task_info
            else:
                task = task_info
                exc = None
            tasks.append(task)
            exit_exceptions.append(exc)

        class FakeAcquire(object):
            def __init__(fa_self, context, node_id, *args, **kwargs):
                # We actually verify these arguments via
                # acquire_mock.call_args_list(). However, this stores the
                # node_id so we can assert we're returning the correct node
                # in __enter__().
                fa_self.node_id = node_id

            def __enter__(fa_self):
                task = tasks.pop(0)
                if isinstance(task, Exception):
                    raise task
                # NOTE(comstud): Not ideal to throw this into
                # a helper, however it's the cleanest way
                # to verify we're dealing with the correct task/node.
                if strutils.is_int_like(fa_self.node_id):
                    self.assertEqual(fa_self.node_id, task.node.id)
                else:
                    self.assertEqual(fa_self.node_id, task.node.uuid)
                return task

            def __exit__(fa_self, exc_typ, exc_val, exc_tb):
                exc = exit_exceptions.pop(0)
                if exc_typ is None and exc is not None:
                    raise exc

        return FakeAcquire


class ServiceSetUpMixin(object):
    def setUp(self):
        super(ServiceSetUpMixin, self).setUp()
        self.hostname = 'test-host'
        self.config(node_locked_retry_attempts=1, group='conductor')
        self.config(node_locked_retry_interval=0, group='conductor')

        self.service = manager.ConductorManager(self.hostname, 'test-topic')

    def _stop_service(self):
        try:
            objects.Conductor.get_by_hostname(self.context, self.hostname)
        except exception.ConductorNotFound:
            return
        self.service.del_host()

    def _start_service(self, start_periodic_tasks=False):
        if start_periodic_tasks:
            self.service.init_host()
        else:
            with mock.patch.object(periodics, 'PeriodicWorker', autospec=True):
                self.service.prepare_host()
                self.service.init_host()
        self.addCleanup(self._stop_service)


def mock_record_keepalive(func_or_class):
    return mock.patch.object(
        manager.ConductorManager,
        '_conductor_service_record_keepalive',
        lambda _: None)(func_or_class)
