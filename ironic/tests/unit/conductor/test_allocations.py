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

"""Unit tests for functionality related to allocations."""

from unittest import mock

import oslo_messaging as messaging
from oslo_utils import uuidutils

from ironic.common import exception
from ironic.conductor import allocations
from ironic.conductor import manager
from ironic.conductor import task_manager
from ironic import objects
from ironic.tests.unit.conductor import mgr_utils
from ironic.tests.unit.db import base as db_base
from ironic.tests.unit.db import utils as db_utils
from ironic.tests.unit.objects import utils as obj_utils


@mgr_utils.mock_record_keepalive
class AllocationTestCase(mgr_utils.ServiceSetUpMixin, db_base.DbTestCase):
    @mock.patch.object(manager.ConductorManager, '_spawn_worker',
                       autospec=True)
    def test_create_allocation(self, mock_spawn):
        # In this test we mock spawn_worker, so that the actual processing does
        # not happen, and the allocation stays in the "allocating" state.
        allocation = obj_utils.get_test_allocation(self.context,
                                                   extra={'test': 'one'})
        self._start_service()

        mock_spawn.assert_any_call(self.service,
                                   self.service._resume_allocations,
                                   mock.ANY)
        mock_spawn.reset_mock()

        res = self.service.create_allocation(self.context, allocation)

        self.assertEqual({'test': 'one'}, res['extra'])
        self.assertEqual('allocating', res['state'])
        self.assertIsNotNone(res['uuid'])
        self.assertEqual(self.service.conductor.id, res['conductor_affinity'])
        res = objects.Allocation.get_by_uuid(self.context, allocation['uuid'])
        self.assertEqual({'test': 'one'}, res['extra'])
        self.assertEqual('allocating', res['state'])
        self.assertIsNotNone(res['uuid'])
        self.assertEqual(self.service.conductor.id, res['conductor_affinity'])

        mock_spawn.assert_called_once_with(self.service,
                                           allocations.do_allocate,
                                           self.context, mock.ANY)

    @mock.patch.object(manager.ConductorManager, '_spawn_worker', mock.Mock())
    @mock.patch.object(allocations, 'backfill_allocation', autospec=True)
    def test_create_allocation_with_node_id(self, mock_backfill):
        node = obj_utils.create_test_node(self.context)
        allocation = obj_utils.get_test_allocation(self.context,
                                                   node_id=node.id)

        self._start_service()
        res = self.service.create_allocation(self.context, allocation)
        mock_backfill.assert_called_once_with(self.context,
                                              allocation,
                                              node.id)

        self.assertEqual('allocating', res['state'])
        self.assertIsNotNone(res['uuid'])
        self.assertEqual(self.service.conductor.id, res['conductor_affinity'])
        # create_allocation purges node_id, and since we stub out
        # backfill_allocation, it does not get populated.
        self.assertIsNone(res['node_id'])
        res = objects.Allocation.get_by_uuid(self.context, allocation['uuid'])
        self.assertEqual('allocating', res['state'])
        self.assertIsNotNone(res['uuid'])
        self.assertEqual(self.service.conductor.id, res['conductor_affinity'])

    def test_destroy_allocation_without_node(self):
        allocation = obj_utils.create_test_allocation(self.context)
        self.service.destroy_allocation(self.context, allocation)
        self.assertRaises(exception.AllocationNotFound,
                          objects.Allocation.get_by_uuid,
                          self.context, allocation['uuid'])

    def test_destroy_allocation_with_node(self):
        node = obj_utils.create_test_node(self.context)
        allocation = obj_utils.create_test_allocation(self.context,
                                                      node_id=node['id'])
        node.instance_uuid = allocation['uuid']
        node.allocation_id = allocation['id']
        node.save()

        self.service.destroy_allocation(self.context, allocation)
        self.assertRaises(exception.AllocationNotFound,
                          objects.Allocation.get_by_uuid,
                          self.context, allocation['uuid'])
        node = objects.Node.get_by_uuid(self.context, node['uuid'])
        self.assertIsNone(node['instance_uuid'])
        self.assertIsNone(node['allocation_id'])

    def test_destroy_allocation_with_active_node(self):
        node = obj_utils.create_test_node(self.context,
                                          provision_state='active')
        allocation = obj_utils.create_test_allocation(self.context,
                                                      node_id=node['id'])
        node.instance_uuid = allocation['uuid']
        node.allocation_id = allocation['id']
        node.save()

        exc = self.assertRaises(messaging.rpc.ExpectedException,
                                self.service.destroy_allocation,
                                self.context, allocation)
        # Compare true exception hidden by @messaging.expected_exceptions
        self.assertEqual(exception.InvalidState, exc.exc_info[0])

        objects.Allocation.get_by_uuid(self.context, allocation['uuid'])
        node = objects.Node.get_by_uuid(self.context, node['uuid'])
        self.assertEqual(allocation['uuid'], node['instance_uuid'])
        self.assertEqual(allocation['id'], node['allocation_id'])

    def test_destroy_allocation_with_transient_node(self):
        node = obj_utils.create_test_node(self.context,
                                          target_provision_state='active',
                                          provision_state='deploying')
        allocation = obj_utils.create_test_allocation(self.context,
                                                      node_id=node['id'])
        node.instance_uuid = allocation['uuid']
        node.allocation_id = allocation['id']
        node.save()

        exc = self.assertRaises(messaging.rpc.ExpectedException,
                                self.service.destroy_allocation,
                                self.context, allocation)
        # Compare true exception hidden by @messaging.expected_exceptions
        self.assertEqual(exception.InvalidState, exc.exc_info[0])

        objects.Allocation.get_by_uuid(self.context, allocation['uuid'])
        node = objects.Node.get_by_uuid(self.context, node['uuid'])
        self.assertEqual(allocation['uuid'], node['instance_uuid'])
        self.assertEqual(allocation['id'], node['allocation_id'])

    def test_destroy_allocation_with_node_in_maintenance(self):
        node = obj_utils.create_test_node(self.context,
                                          provision_state='active',
                                          maintenance=True)
        allocation = obj_utils.create_test_allocation(self.context,
                                                      node_id=node['id'])
        node.instance_uuid = allocation['uuid']
        node.allocation_id = allocation['id']
        node.save()

        self.service.destroy_allocation(self.context, allocation)
        self.assertRaises(exception.AllocationNotFound,
                          objects.Allocation.get_by_uuid,
                          self.context, allocation['uuid'])
        node = objects.Node.get_by_uuid(self.context, node['uuid'])
        self.assertIsNone(node['instance_uuid'])
        self.assertIsNone(node['allocation_id'])

    @mock.patch.object(allocations, 'do_allocate', autospec=True)
    def test_resume_allocations(self, mock_allocate):
        another_conductor = obj_utils.create_test_conductor(
            self.context, id=42, hostname='another-host')

        self._start_service()

        obj_utils.create_test_allocation(
            self.context,
            state='active',
            conductor_affinity=self.service.conductor.id)
        obj_utils.create_test_allocation(
            self.context,
            state='allocating',
            conductor_affinity=another_conductor.id)
        allocation = obj_utils.create_test_allocation(
            self.context,
            state='allocating',
            conductor_affinity=self.service.conductor.id)

        self.service._resume_allocations(self.context)

        mock_allocate.assert_called_once_with(self.context, mock.ANY)
        actual = mock_allocate.call_args[0][1]
        self.assertEqual(allocation.uuid, actual.uuid)
        self.assertIsInstance(allocation, objects.Allocation)

    @mock.patch.object(allocations, 'do_allocate', autospec=True)
    def test_check_orphaned_allocations(self, mock_allocate):
        alive_conductor = obj_utils.create_test_conductor(
            self.context, id=42, hostname='alive')
        dead_conductor = obj_utils.create_test_conductor(
            self.context, id=43, hostname='dead')

        obj_utils.create_test_allocation(
            self.context,
            state='allocating',
            conductor_affinity=alive_conductor.id)
        allocation = obj_utils.create_test_allocation(
            self.context,
            state='allocating',
            conductor_affinity=dead_conductor.id)

        self._start_service()
        with mock.patch.object(self.dbapi, 'get_offline_conductors',
                               autospec=True) as mock_conds:
            mock_conds.return_value = [dead_conductor.id]
            self.service._check_orphan_allocations(self.context)

        mock_allocate.assert_called_once_with(self.context, mock.ANY)
        actual = mock_allocate.call_args[0][1]
        self.assertEqual(allocation.uuid, actual.uuid)
        self.assertIsInstance(allocation, objects.Allocation)

        allocation = self.dbapi.get_allocation_by_id(allocation.id)
        self.assertEqual(self.service.conductor.id,
                         allocation.conductor_affinity)


@mock.patch('time.sleep', lambda _: None)
class DoAllocateTestCase(db_base.DbTestCase):
    def test_success(self):
        node = obj_utils.create_test_node(self.context,
                                          power_state='power on',
                                          resource_class='x-large',
                                          provision_state='available')
        allocation = obj_utils.create_test_allocation(self.context,
                                                      resource_class='x-large')

        allocations.do_allocate(self.context, allocation)

        allocation = objects.Allocation.get_by_uuid(self.context,
                                                    allocation['uuid'])
        self.assertIsNone(allocation['last_error'])
        self.assertEqual('active', allocation['state'])

        node = objects.Node.get_by_uuid(self.context, node['uuid'])
        self.assertEqual(allocation['uuid'], node['instance_uuid'])
        self.assertEqual(allocation['id'], node['allocation_id'])

    def test_with_traits(self):
        obj_utils.create_test_node(self.context,
                                   uuid=uuidutils.generate_uuid(),
                                   power_state='power on',
                                   resource_class='x-large',
                                   provision_state='available')
        node = obj_utils.create_test_node(self.context,
                                          uuid=uuidutils.generate_uuid(),
                                          power_state='power on',
                                          resource_class='x-large',
                                          provision_state='available')
        db_utils.create_test_node_traits(['tr1', 'tr2'], node_id=node.id)

        allocation = obj_utils.create_test_allocation(self.context,
                                                      resource_class='x-large',
                                                      traits=['tr2'])

        allocations.do_allocate(self.context, allocation)

        allocation = objects.Allocation.get_by_uuid(self.context,
                                                    allocation['uuid'])
        self.assertIsNone(allocation['last_error'])
        self.assertEqual('active', allocation['state'])

        node = objects.Node.get_by_uuid(self.context, node['uuid'])
        self.assertEqual(allocation['uuid'], node['instance_uuid'])
        self.assertEqual(allocation['id'], node['allocation_id'])
        self.assertEqual(allocation['traits'], ['tr2'])

    def test_with_candidates(self):
        obj_utils.create_test_node(self.context,
                                   uuid=uuidutils.generate_uuid(),
                                   power_state='power on',
                                   resource_class='x-large',
                                   provision_state='available')
        node = obj_utils.create_test_node(self.context,
                                          uuid=uuidutils.generate_uuid(),
                                          power_state='power on',
                                          resource_class='x-large',
                                          provision_state='available')

        allocation = obj_utils.create_test_allocation(
            self.context, resource_class='x-large',
            candidate_nodes=[node['uuid']])

        allocations.do_allocate(self.context, allocation)

        allocation = objects.Allocation.get_by_uuid(self.context,
                                                    allocation['uuid'])
        self.assertIsNone(allocation['last_error'])
        self.assertEqual('active', allocation['state'])

        node = objects.Node.get_by_uuid(self.context, node['uuid'])
        self.assertEqual(allocation['uuid'], node['instance_uuid'])
        self.assertEqual(allocation['id'], node['allocation_id'])
        self.assertEqual([node['uuid']], allocation['candidate_nodes'])

    @mock.patch.object(task_manager, 'acquire', autospec=True,
                       side_effect=task_manager.acquire)
    def test_nodes_filtered_out(self, mock_acquire):
        # Resource class does not match
        obj_utils.create_test_node(self.context,
                                   uuid=uuidutils.generate_uuid(),
                                   resource_class='x-small',
                                   power_state='power off',
                                   provision_state='available')
        # Provision state is not available
        obj_utils.create_test_node(self.context,
                                   uuid=uuidutils.generate_uuid(),
                                   resource_class='x-large',
                                   power_state='power off',
                                   provision_state='manageable')
        # Power state is undefined
        obj_utils.create_test_node(self.context,
                                   uuid=uuidutils.generate_uuid(),
                                   resource_class='x-large',
                                   power_state=None,
                                   provision_state='available')
        # Maintenance mode is on
        obj_utils.create_test_node(self.context,
                                   uuid=uuidutils.generate_uuid(),
                                   maintenance=True,
                                   resource_class='x-large',
                                   power_state='power off',
                                   provision_state='available')
        # Already associated
        obj_utils.create_test_node(self.context,
                                   uuid=uuidutils.generate_uuid(),
                                   instance_uuid=uuidutils.generate_uuid(),
                                   resource_class='x-large',
                                   power_state='power off',
                                   provision_state='available')

        allocation = obj_utils.create_test_allocation(self.context,
                                                      resource_class='x-large')
        allocations.do_allocate(self.context, allocation)
        self.assertIn('no available nodes', allocation['last_error'])
        self.assertIn('x-large', allocation['last_error'])
        self.assertEqual('error', allocation['state'])

        # All nodes are filtered out on the database level.
        self.assertFalse(mock_acquire.called)

    @mock.patch.object(task_manager, 'acquire', autospec=True,
                       side_effect=task_manager.acquire)
    def test_nodes_filtered_out_project(self, mock_acquire):
        # Owner and lessee do not match
        obj_utils.create_test_node(self.context,
                                   uuid=uuidutils.generate_uuid(),
                                   owner='54321',
                                   resource_class='x-large',
                                   power_state='power off',
                                   provision_state='available')
        obj_utils.create_test_node(self.context,
                                   uuid=uuidutils.generate_uuid(),
                                   lessee='54321',
                                   resource_class='x-large',
                                   power_state='power off',
                                   provision_state='available')

        allocation = obj_utils.create_test_allocation(self.context,
                                                      resource_class='x-large',
                                                      owner='12345')
        allocations.do_allocate(self.context, allocation)
        self.assertIn('no available nodes', allocation['last_error'])
        self.assertIn('x-large', allocation['last_error'])
        self.assertEqual('error', allocation['state'])

        # All nodes are filtered out on the database level.
        self.assertFalse(mock_acquire.called)

    @mock.patch.object(task_manager, 'acquire', autospec=True,
                       side_effect=task_manager.acquire)
    def test_nodes_locked(self, mock_acquire):
        self.config(node_locked_retry_attempts=2, group='conductor')
        node1 = obj_utils.create_test_node(self.context,
                                           uuid=uuidutils.generate_uuid(),
                                           maintenance=False,
                                           resource_class='x-large',
                                           power_state='power off',
                                           provision_state='available',
                                           reservation='example.com')
        node2 = obj_utils.create_test_node(self.context,
                                           uuid=uuidutils.generate_uuid(),
                                           resource_class='x-large',
                                           power_state='power off',
                                           provision_state='available',
                                           reservation='example.com')

        allocation = obj_utils.create_test_allocation(self.context,
                                                      resource_class='x-large')
        allocations.do_allocate(self.context, allocation)
        self.assertIn('could not reserve any of 2', allocation['last_error'])
        self.assertEqual('error', allocation['state'])

        self.assertEqual(6, mock_acquire.call_count)
        # NOTE(dtantsur): node are tried in random order by design, so we
        # cannot directly use assert_has_calls. Check that all nodes are tried
        # before going into retries (rather than each tried 3 times in a row).
        nodes = [call[0][1] for call in mock_acquire.call_args_list]
        for offset in (0, 2, 4):
            self.assertEqual(set(nodes[offset:offset + 2]),
                             {node1.uuid, node2.uuid})

    @mock.patch.object(task_manager, 'acquire', autospec=True)
    def test_nodes_changed_after_lock(self, mock_acquire):
        nodes = [obj_utils.create_test_node(self.context,
                                            uuid=uuidutils.generate_uuid(),
                                            resource_class='x-large',
                                            power_state='power off',
                                            provision_state='available')
                 for _ in range(5)]
        for node in nodes:
            db_utils.create_test_node_trait(trait='tr1', node_id=node.id)

        # Modify nodes in-memory so that they no longer match the allocation:

        # Resource class does not match
        nodes[0].resource_class = 'x-small'
        # Provision state is not available
        nodes[1].provision_state = 'deploying'
        # Maintenance mode is on
        nodes[2].maintenance = True
        # Already associated
        nodes[3].instance_uuid = uuidutils.generate_uuid()
        # Traits changed
        nodes[4].traits.objects[:] = []

        mock_acquire.side_effect = [
            mock.MagicMock(**{'__enter__.return_value.node': node})
            for node in nodes
        ]

        allocation = obj_utils.create_test_allocation(self.context,
                                                      resource_class='x-large',
                                                      traits=['tr1'])
        allocations.do_allocate(self.context, allocation)
        self.assertIn('all nodes were filtered out', allocation['last_error'])
        self.assertEqual('error', allocation['state'])

        # No retries for these failures.
        self.assertEqual(5, mock_acquire.call_count)

    @mock.patch.object(task_manager, 'acquire', autospec=True,
                       side_effect=task_manager.acquire)
    def test_nodes_candidates_do_not_match(self, mock_acquire):
        obj_utils.create_test_node(self.context,
                                   uuid=uuidutils.generate_uuid(),
                                   resource_class='x-large',
                                   power_state='power off',
                                   provision_state='available')
        # Resource class does not match
        node = obj_utils.create_test_node(self.context,
                                          uuid=uuidutils.generate_uuid(),
                                          power_state='power on',
                                          resource_class='x-small',
                                          provision_state='available')

        allocation = obj_utils.create_test_allocation(
            self.context, resource_class='x-large',
            candidate_nodes=[node['uuid']])

        allocations.do_allocate(self.context, allocation)
        self.assertIn('none of the requested nodes', allocation['last_error'])
        self.assertIn('x-large', allocation['last_error'])
        self.assertEqual('error', allocation['state'])

        # All nodes are filtered out on the database level.
        self.assertFalse(mock_acquire.called)

    def test_name_match_first(self):
        obj_utils.create_test_node(self.context,
                                   uuid=uuidutils.generate_uuid(),
                                   name='node-1',
                                   power_state='power on',
                                   resource_class='x-large',
                                   provision_state='available')
        node = obj_utils.create_test_node(self.context,
                                          uuid=uuidutils.generate_uuid(),
                                          name='node-2',
                                          power_state='power on',
                                          resource_class='x-large',
                                          provision_state='available')
        obj_utils.create_test_node(self.context,
                                   uuid=uuidutils.generate_uuid(),
                                   name='node-3',
                                   power_state='power on',
                                   resource_class='x-large',
                                   provision_state='available')
        allocation = obj_utils.create_test_allocation(self.context,
                                                      name='node-2',
                                                      resource_class='x-large')

        allocations.do_allocate(self.context, allocation)

        allocation = objects.Allocation.get_by_uuid(self.context,
                                                    allocation['uuid'])
        self.assertIsNone(allocation['last_error'])
        self.assertEqual('active', allocation['state'])

        node = objects.Node.get_by_uuid(self.context, node['uuid'])
        self.assertEqual(allocation['uuid'], node['instance_uuid'])
        self.assertEqual(allocation['id'], node['allocation_id'])
        self.assertEqual('node-2', node['name'])


class BackfillAllocationTestCase(db_base.DbTestCase):
    def test_with_associated_node(self):
        uuid = uuidutils.generate_uuid()
        node = obj_utils.create_test_node(self.context,
                                          instance_uuid=uuid,
                                          resource_class='x-large',
                                          provision_state='active')
        allocation = obj_utils.create_test_allocation(self.context,
                                                      uuid=uuid,
                                                      resource_class='x-large')

        allocations.backfill_allocation(self.context, allocation, node.id)

        allocation = objects.Allocation.get_by_uuid(self.context,
                                                    allocation['uuid'])
        self.assertIsNone(allocation['last_error'])
        self.assertEqual('active', allocation['state'])

        node = objects.Node.get_by_uuid(self.context, node['uuid'])
        self.assertEqual(allocation['uuid'], node['instance_uuid'])
        self.assertEqual(allocation['id'], node['allocation_id'])

    def test_with_unassociated_node(self):
        node = obj_utils.create_test_node(self.context,
                                          instance_uuid=None,
                                          resource_class='x-large',
                                          provision_state='active')
        allocation = obj_utils.create_test_allocation(self.context,
                                                      resource_class='x-large')

        allocations.backfill_allocation(self.context, allocation, node.id)

        allocation = objects.Allocation.get_by_uuid(self.context,
                                                    allocation['uuid'])
        self.assertIsNone(allocation['last_error'])
        self.assertEqual('active', allocation['state'])

        node = objects.Node.get_by_uuid(self.context, node['uuid'])
        self.assertEqual(allocation['uuid'], node['instance_uuid'])
        self.assertEqual(allocation['id'], node['allocation_id'])

    def test_with_candidate_nodes(self):
        node = obj_utils.create_test_node(self.context,
                                          instance_uuid=None,
                                          resource_class='x-large',
                                          provision_state='active')
        allocation = obj_utils.create_test_allocation(
            self.context, candidate_nodes=[node.uuid],
            resource_class='x-large')

        allocations.backfill_allocation(self.context, allocation, node.id)

        allocation = objects.Allocation.get_by_uuid(self.context,
                                                    allocation['uuid'])
        self.assertIsNone(allocation['last_error'])
        self.assertEqual('active', allocation['state'])

        node = objects.Node.get_by_uuid(self.context, node['uuid'])
        self.assertEqual(allocation['uuid'], node['instance_uuid'])
        self.assertEqual(allocation['id'], node['allocation_id'])

    def test_without_resource_class(self):
        uuid = uuidutils.generate_uuid()
        node = obj_utils.create_test_node(self.context,
                                          instance_uuid=uuid,
                                          resource_class='x-large',
                                          provision_state='active')
        allocation = obj_utils.create_test_allocation(self.context,
                                                      uuid=uuid,
                                                      resource_class=None)

        allocations.backfill_allocation(self.context, allocation, node.id)

        allocation = objects.Allocation.get_by_uuid(self.context,
                                                    allocation['uuid'])
        self.assertIsNone(allocation['last_error'])
        self.assertEqual('active', allocation['state'])

        node = objects.Node.get_by_uuid(self.context, node['uuid'])
        self.assertEqual(allocation['uuid'], node['instance_uuid'])
        self.assertEqual(allocation['id'], node['allocation_id'])

    def test_node_associated_with_another_instance(self):
        other_uuid = uuidutils.generate_uuid()
        node = obj_utils.create_test_node(self.context,
                                          instance_uuid=other_uuid,
                                          resource_class='x-large',
                                          provision_state='active')
        allocation = obj_utils.create_test_allocation(self.context,
                                                      resource_class='x-large')

        self.assertRaises(exception.NodeAssociated,
                          allocations.backfill_allocation,
                          self.context, allocation, node.id)

        allocation = objects.Allocation.get_by_uuid(self.context,
                                                    allocation['uuid'])
        self.assertEqual('error', allocation['state'])
        self.assertIn('associated', allocation['last_error'])
        self.assertIsNone(allocation['node_id'])

        node = objects.Node.get_by_uuid(self.context, node['uuid'])
        self.assertEqual(other_uuid, node['instance_uuid'])
        self.assertIsNone(node['allocation_id'])

    def test_non_existing_node(self):
        allocation = obj_utils.create_test_allocation(self.context,
                                                      resource_class='x-large')

        self.assertRaises(exception.NodeNotFound,
                          allocations.backfill_allocation,
                          self.context, allocation, 42)

        allocation = objects.Allocation.get_by_uuid(self.context,
                                                    allocation['uuid'])
        self.assertEqual('error', allocation['state'])
        self.assertIn('Node 42 could not be found', allocation['last_error'])
        self.assertIsNone(allocation['node_id'])

    def test_uuid_associated_with_another_instance(self):
        uuid = uuidutils.generate_uuid()
        obj_utils.create_test_node(self.context,
                                   uuid=uuidutils.generate_uuid(),
                                   instance_uuid=uuid,
                                   resource_class='x-large',
                                   provision_state='active')
        node = obj_utils.create_test_node(self.context,
                                          uuid=uuidutils.generate_uuid(),
                                          resource_class='x-large',
                                          provision_state='active')
        allocation = obj_utils.create_test_allocation(self.context,
                                                      uuid=uuid,
                                                      resource_class='x-large')

        self.assertRaises(exception.InstanceAssociated,
                          allocations.backfill_allocation,
                          self.context, allocation, node.id)

        allocation = objects.Allocation.get_by_uuid(self.context,
                                                    allocation['uuid'])
        self.assertEqual('error', allocation['state'])
        self.assertIn('associated', allocation['last_error'])
        self.assertIsNone(allocation['node_id'])

        node = objects.Node.get_by_uuid(self.context, node['uuid'])
        self.assertIsNone(node['instance_uuid'])
        self.assertIsNone(node['allocation_id'])

    def test_resource_class_mismatch(self):
        node = obj_utils.create_test_node(self.context,
                                          resource_class='x-small',
                                          provision_state='active')
        allocation = obj_utils.create_test_allocation(self.context,
                                                      resource_class='x-large')

        self.assertRaises(exception.AllocationFailed,
                          allocations.backfill_allocation,
                          self.context, allocation, node.id)

        allocation = objects.Allocation.get_by_uuid(self.context,
                                                    allocation['uuid'])
        self.assertEqual('error', allocation['state'])
        self.assertIn('resource class', allocation['last_error'])
        self.assertIsNone(allocation['node_id'])

        node = objects.Node.get_by_uuid(self.context, node['uuid'])
        self.assertIsNone(node['instance_uuid'])
        self.assertIsNone(node['allocation_id'])

    def test_traits_mismatch(self):
        node = obj_utils.create_test_node(self.context,
                                          resource_class='x-large',
                                          provision_state='active')
        db_utils.create_test_node_traits(['tr1', 'tr2'], node_id=node.id)
        allocation = obj_utils.create_test_allocation(self.context,
                                                      resource_class='x-large',
                                                      traits=['tr1', 'tr3'])

        self.assertRaises(exception.AllocationFailed,
                          allocations.backfill_allocation,
                          self.context, allocation, node.id)

        allocation = objects.Allocation.get_by_uuid(self.context,
                                                    allocation['uuid'])
        self.assertEqual('error', allocation['state'])
        self.assertIn('traits', allocation['last_error'])
        self.assertIsNone(allocation['node_id'])

        node = objects.Node.get_by_uuid(self.context, node['uuid'])
        self.assertIsNone(node['instance_uuid'])
        self.assertIsNone(node['allocation_id'])

    def test_state_not_active(self):
        node = obj_utils.create_test_node(self.context,
                                          resource_class='x-large',
                                          provision_state='available')
        allocation = obj_utils.create_test_allocation(self.context,
                                                      resource_class='x-large')

        self.assertRaises(exception.AllocationFailed,
                          allocations.backfill_allocation,
                          self.context, allocation, node.id)

        allocation = objects.Allocation.get_by_uuid(self.context,
                                                    allocation['uuid'])
        self.assertEqual('error', allocation['state'])
        self.assertIn('must be in the "active" state',
                      allocation['last_error'])
        self.assertIsNone(allocation['node_id'])

        node = objects.Node.get_by_uuid(self.context, node['uuid'])
        self.assertIsNone(node['instance_uuid'])
        self.assertIsNone(node['allocation_id'])

    def test_candidate_nodes_mismatch(self):
        node = obj_utils.create_test_node(self.context,
                                          resource_class='x-large',
                                          provision_state='active')
        allocation = obj_utils.create_test_allocation(
            self.context,
            candidate_nodes=[uuidutils.generate_uuid()],
            resource_class='x-large')

        self.assertRaises(exception.AllocationFailed,
                          allocations.backfill_allocation,
                          self.context, allocation, node.id)

        allocation = objects.Allocation.get_by_uuid(self.context,
                                                    allocation['uuid'])
        self.assertEqual('error', allocation['state'])
        self.assertIn('Candidate nodes', allocation['last_error'])
        self.assertIsNone(allocation['node_id'])

        node = objects.Node.get_by_uuid(self.context, node['uuid'])
        self.assertIsNone(node['instance_uuid'])
        self.assertIsNone(node['allocation_id'])
