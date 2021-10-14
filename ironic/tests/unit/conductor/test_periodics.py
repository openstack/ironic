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

from unittest import mock

from oslo_utils import uuidutils

from ironic.common import context as ironic_context
from ironic.conductor import base_manager
from ironic.conductor import periodics
from ironic.conductor import task_manager
from ironic.tests.unit.db import base as db_base
from ironic.tests.unit.objects import utils as obj_utils


_FILTERS = {'maintenance': False}


class PeriodicTestService(base_manager.BaseConductorManager):

    def __init__(self, test):
        self.test = test
        self.nodes = []

    @periodics.node_periodic(purpose="herding cats", spacing=42)
    def simple(self, task, context):
        self.test.assertIsInstance(context, ironic_context.RequestContext)
        self.test.assertTrue(task.shared)
        self.nodes.append(task.node.uuid)

    @periodics.node_periodic(purpose="herding cats", spacing=42,
                             shared_task=False, filters=_FILTERS)
    def exclusive(self, task, context):
        self.test.assertIsInstance(context, ironic_context.RequestContext)
        self.test.assertFalse(task.shared)
        self.nodes.append(task.node.uuid)

    @periodics.node_periodic(purpose="never running", spacing=42,
                             predicate=lambda n: n.cat != 'meow',
                             predicate_extra_fields=['cat'])
    def never_run(self, task, context):
        self.test.fail(f"Was not supposed to run, ran with {task.node}")

    @periodics.node_periodic(purpose="herding cats", spacing=42, limit=3)
    def limit(self, task, context):
        self.test.assertIsInstance(context, ironic_context.RequestContext)
        self.test.assertTrue(task.shared)
        self.nodes.append(task.node.uuid)
        if task.node.uuid == 'stop':
            raise periodics.Stop()


@mock.patch.object(PeriodicTestService, 'iter_nodes', autospec=True)
class NodePeriodicTestCase(db_base.DbTestCase):

    def setUp(self):
        super().setUp()
        self.service = PeriodicTestService(self)
        self.ctx = ironic_context.get_admin_context()
        self.uuid = uuidutils.generate_uuid()
        self.node = obj_utils.create_test_node(self.context, uuid=self.uuid)

    def test_simple(self, mock_iter_nodes):
        mock_iter_nodes.return_value = iter([
            (uuidutils.generate_uuid(), 'driver1', ''),
            (self.uuid, 'driver2', 'group'),
        ])

        self.service.simple(self.ctx)

        mock_iter_nodes.assert_called_once_with(self.service,
                                                filters=None, fields=())
        self.assertEqual([self.uuid], self.service.nodes)

    def test_exclusive(self, mock_iter_nodes):
        mock_iter_nodes.return_value = iter([
            (uuidutils.generate_uuid(), 'driver1', ''),
            (self.uuid, 'driver2', 'group'),
        ])

        self.service.exclusive(self.ctx)

        mock_iter_nodes.assert_called_once_with(self.service,
                                                filters=_FILTERS,
                                                fields=())
        self.assertEqual([self.uuid], self.service.nodes)

    @mock.patch.object(task_manager, 'acquire', autospec=True)
    def test_never_run(self, mock_acquire, mock_iter_nodes):
        mock_iter_nodes.return_value = iter([
            (self.uuid, 'driver2', 'group', 'meow'),
        ])

        self.service.never_run(self.ctx)

        mock_iter_nodes.assert_called_once_with(self.service,
                                                filters=None,
                                                fields=['cat'])
        self.assertEqual([], self.service.nodes)
        mock_acquire.assert_not_called()

    @mock.patch.object(task_manager, 'acquire', autospec=True)
    def test_limit(self, mock_acquire, mock_iter_nodes):
        mock_iter_nodes.return_value = iter([
            (self.uuid, 'driver1', ''),
        ] * 10)
        mock_acquire.return_value.__enter__.return_value.node.uuid = self.uuid

        self.service.limit(self.ctx)

        mock_iter_nodes.assert_called_once_with(self.service,
                                                filters=None, fields=())
        self.assertEqual([self.uuid] * 3, self.service.nodes)

    @mock.patch.object(task_manager, 'acquire', autospec=True)
    def test_stop(self, mock_acquire, mock_iter_nodes):
        mock_iter_nodes.return_value = iter([
            (self.uuid, 'driver1', ''),
        ] * 10)
        mock_acquire.return_value.__enter__.return_value.node.uuid = 'stop'

        self.service.limit(self.ctx)

        mock_iter_nodes.assert_called_once_with(self.service,
                                                filters=None, fields=())
        self.assertEqual(['stop'], self.service.nodes)
