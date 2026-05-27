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
from oslo_config import cfg

from ironic.conductor import base_manager
from ironic.conductor import periodics

CONF = cfg.CONF
from ironic.conductor import task_manager
from ironic.drivers.modules import fake
from ironic.tests.unit.db import base as db_base
from ironic.tests.unit.objects import utils as obj_utils


_FILTERS = {'maintenance': False}


class TestLazyPeriodicAttributes(db_base.DbTestCase):

    def test_refresh_periodic_attributes_resolves_callables(self):
        @periodics.periodic(spacing=lambda: 120,
                            enabled=lambda: CONF.sensor_data.send_sensor_data)
        def sample_task():
            return None

        self.assertFalse(sample_task._is_periodic)

        CONF.set_override('send_sensor_data', True, group='sensor_data')
        periodics.refresh_periodic_attributes(sample_task)

        self.assertTrue(sample_task._is_periodic)
        self.assertEqual(120, sample_task._periodic_spacing)

        CONF.set_override('send_sensor_data', False, group='sensor_data')
        periodics.refresh_periodic_attributes(sample_task)
        self.assertFalse(sample_task._is_periodic)


class PeriodicTestService(base_manager.BaseConductorManager):

    def __init__(self, test):
        self.test = test
        self.nodes = []

    @periodics.node_periodic(purpose="herding cats", spacing=42)
    def simple(self, task, context):
        self.test.assertIsInstance(context, ironic_context.RequestContext)
        self.test.assertTrue(task.shared)
        # This may raise
        task.upgrade_lock()
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


class PeriodicTestInterface(fake.FakePower):

    def __init__(self, test):
        self.test = test
        self.nodes = []

    @periodics.node_periodic(purpose="herding cats", spacing=42)
    def simple(self, task, manager, context):
        self.test.assertIsInstance(manager, PeriodicTestService)
        self.test.assertIsInstance(context, ironic_context.RequestContext)
        self.nodes.append(task.node.uuid)


@mock.patch.object(PeriodicTestService, 'iter_nodes', autospec=True)
class NodePeriodicTestCase(db_base.DbTestCase):

    def setUp(self):
        super().setUp()
        self.service = PeriodicTestService(self)
        self.ctx = ironic_context.get_admin_context()
        self.uuid = uuidutils.generate_uuid()
        self.node = obj_utils.create_test_node(self.context, uuid=self.uuid)

    @mock.patch.object(periodics.LOG, 'info', autospec=True)
    def test_simple(self, mock_log, mock_iter_nodes):
        node2 = obj_utils.create_test_node(self.context,
                                           uuid=uuidutils.generate_uuid(),
                                           reservation='host0')
        mock_iter_nodes.return_value = iter([
            (uuidutils.generate_uuid(), 'driver1', ''),
            (self.uuid, 'driver2', 'group'),
            (node2.uuid, 'driver3', 'group'),
        ])

        self.service.simple(self.ctx)

        mock_iter_nodes.assert_called_once_with(self.service,
                                                filters=None, fields=())
        self.assertEqual([self.uuid], self.service.nodes)
        # 1 node not found, 1 locked
        self.assertEqual(2, mock_log.call_count)

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

    @mock.patch.object(task_manager, 'acquire', autospec=True)
    def test_interface_check(self, mock_acquire, mock_iter_nodes):
        mock_iter_nodes.return_value = iter([
            (uuidutils.generate_uuid(), 'driver1', ''),
            (self.uuid, 'driver2', 'group'),
        ])
        iface = PeriodicTestInterface(self)
        tasks = [
            mock.Mock(spec=task_manager.TaskManager,
                      # This will not match the subclass
                      driver=mock.Mock(power=fake.FakePower())),
            mock.Mock(spec=task_manager.TaskManager,
                      node=self.node,
                      driver=mock.Mock(power=iface)),
        ]
        mock_acquire.side_effect = [
            mock.MagicMock(**{'__enter__.return_value': task})
            for task in tasks
        ]

        iface.simple(self.service, self.context)

        mock_iter_nodes.assert_called_once_with(self.service,
                                                filters=None, fields=())
        self.assertEqual([self.uuid], iface.nodes)
