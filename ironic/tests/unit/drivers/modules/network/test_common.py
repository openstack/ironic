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

import json
import os
from unittest import mock

from oslo_config import cfg
from oslo_utils import uuidutils

from ironic.common import exception
from ironic.common import neutron as neutron_common
from ironic.common import states
from ironic.conductor import task_manager
from ironic.drivers.modules.network import common
from ironic.tests.unit.db import base as db_base
from ironic.tests.unit.objects import utils as obj_utils

CONF = cfg.CONF


class TestCommonFunctions(db_base.DbTestCase):

    def setUp(self):
        super(TestCommonFunctions, self).setUp()
        self.node = obj_utils.create_test_node(self.context,
                                               network_interface='neutron')
        self.port = obj_utils.create_test_port(
            self.context, node_id=self.node.id, address='52:54:00:cf:2d:32')
        self.vif_id = "fake_vif_id"
        self.client = mock.MagicMock()

    def _objects_setup(self, set_physnets):
        pg1 = obj_utils.create_test_portgroup(
            self.context, node_id=self.node.id)
        pg1_ports = []
        # This portgroup contains 2 ports, both of them without VIF. The ports
        # are assigned to physnet physnet1.
        physical_network = 'physnet1' if set_physnets else None
        for i in range(2):
            pg1_ports.append(obj_utils.create_test_port(
                self.context, node_id=self.node.id,
                address='52:54:00:cf:2d:0%d' % i,
                physical_network=physical_network,
                uuid=uuidutils.generate_uuid(), portgroup_id=pg1.id))
        pg2 = obj_utils.create_test_portgroup(
            self.context, node_id=self.node.id, address='00:54:00:cf:2d:04',
            name='foo2', uuid=uuidutils.generate_uuid())
        pg2_ports = []
        # This portgroup contains 3 ports, one of them with 'some-vif'
        # attached, so the two free ones should be considered standalone.
        # The ports are assigned physnet physnet2.
        physical_network = 'physnet2' if set_physnets else None
        for i in range(2, 4):
            pg2_ports.append(obj_utils.create_test_port(
                self.context, node_id=self.node.id,
                address='52:54:00:cf:2d:0%d' % i,
                physical_network=physical_network,
                uuid=uuidutils.generate_uuid(), portgroup_id=pg2.id))
        pg2_ports.append(obj_utils.create_test_port(
            self.context, node_id=self.node.id,
            address='52:54:00:cf:2d:04',
            physical_network=physical_network,
            internal_info={'tenant_vif_port_id': 'some-vif'},
            uuid=uuidutils.generate_uuid(), portgroup_id=pg2.id))
        # This portgroup has 'some-vif-2' attached to it and contains one port,
        # so neither portgroup nor port can be considered free. The ports are
        # assigned physnet3.
        physical_network = 'physnet3' if set_physnets else None
        pg3 = obj_utils.create_test_portgroup(
            self.context, node_id=self.node.id, address='00:54:00:cf:2d:05',
            name='foo3', uuid=uuidutils.generate_uuid(),
            internal_info={common.TENANT_VIF_KEY: 'some-vif-2'})
        pg3_ports = [obj_utils.create_test_port(
            self.context, node_id=self.node.id,
            address='52:54:00:cf:2d:05', uuid=uuidutils.generate_uuid(),
            physical_network=physical_network,
            portgroup_id=pg3.id)]
        return pg1, pg1_ports, pg2, pg2_ports, pg3, pg3_ports

    def test__get_free_portgroups_and_ports_no_port_physnets(self):
        self.node.network_interface = 'flat'
        self.node.save()
        pg1, pg1_ports, pg2, pg2_ports, pg3, pg3_ports = self._objects_setup(
            set_physnets=False)
        with task_manager.acquire(self.context, self.node.id) as task:
            free_port_like_objs = (
                common._get_free_portgroups_and_ports(task, self.vif_id,
                                                      {'anyphysnet'}))
        self.assertCountEqual(
            [pg1.uuid, self.port.uuid] + [p.uuid for p in pg2_ports[:2]],
            [p.uuid for p in free_port_like_objs])

    def test__get_free_portgroups_and_ports_no_physnets(self):
        self.node.network_interface = 'flat'
        self.node.save()
        pg1, pg1_ports, pg2, pg2_ports, pg3, pg3_ports = self._objects_setup(
            set_physnets=True)
        with task_manager.acquire(self.context, self.node.id) as task:
            free_port_like_objs = (
                common._get_free_portgroups_and_ports(task, self.vif_id,
                                                      set()))
        self.assertCountEqual(
            [pg1.uuid, self.port.uuid] + [p.uuid for p in pg2_ports[:2]],
            [p.uuid for p in free_port_like_objs])

    def test__get_free_portgroups_and_ports_no_matching_physnet(self):
        self.node.network_interface = 'flat'
        self.node.save()
        pg1, pg1_ports, pg2, pg2_ports, pg3, pg3_ports = self._objects_setup(
            set_physnets=True)
        with task_manager.acquire(self.context, self.node.id) as task:
            free_port_like_objs = (
                common._get_free_portgroups_and_ports(task, self.vif_id,
                                                      {'notaphysnet'}))
        self.assertCountEqual(
            [self.port.uuid],
            [p.uuid for p in free_port_like_objs])

    def test__get_free_portgroups_and_ports_physnet1(self):
        self.node.network_interface = 'flat'
        self.node.save()
        pg1, pg1_ports, pg2, pg2_ports, pg3, pg3_ports = self._objects_setup(
            set_physnets=True)
        with task_manager.acquire(self.context, self.node.id) as task:
            free_port_like_objs = (
                common._get_free_portgroups_and_ports(task, self.vif_id,
                                                      {'physnet1'}))
        self.assertCountEqual(
            [pg1.uuid, self.port.uuid],
            [p.uuid for p in free_port_like_objs])

    def test__get_free_portgroups_and_ports_physnet2(self):
        self.node.network_interface = 'flat'
        self.node.save()
        pg1, pg1_ports, pg2, pg2_ports, pg3, pg3_ports = self._objects_setup(
            set_physnets=True)
        with task_manager.acquire(self.context, self.node.id) as task:
            free_port_like_objs = (
                common._get_free_portgroups_and_ports(task, self.vif_id,
                                                      {'physnet2'}))
        self.assertCountEqual(
            [self.port.uuid] + [p.uuid for p in pg2_ports[:2]],
            [p.uuid for p in free_port_like_objs])

    def test__get_free_portgroups_and_ports_physnet3(self):
        self.node.network_interface = 'flat'
        self.node.save()
        pg1, pg1_ports, pg2, pg2_ports, pg3, pg3_ports = self._objects_setup(
            set_physnets=True)
        with task_manager.acquire(self.context, self.node.id) as task:
            free_port_like_objs = (
                common._get_free_portgroups_and_ports(task, self.vif_id,
                                                      {'physnet3'}))
        self.assertCountEqual(
            [self.port.uuid], [p.uuid for p in free_port_like_objs])

    def test__get_free_portgroups_and_ports_all_physnets(self):
        self.node.network_interface = 'flat'
        self.node.save()
        pg1, pg1_ports, pg2, pg2_ports, pg3, pg3_ports = self._objects_setup(
            set_physnets=True)
        physnets = {'physnet1', 'physnet2', 'physnet3'}
        with task_manager.acquire(self.context, self.node.id) as task:
            free_port_like_objs = (
                common._get_free_portgroups_and_ports(task, self.vif_id,
                                                      physnets))
        self.assertCountEqual(
            [pg1.uuid, self.port.uuid] + [p.uuid for p in pg2_ports[:2]],
            [p.uuid for p in free_port_like_objs])

    @mock.patch.object(neutron_common, 'validate_port_info', autospec=True)
    def test__get_free_portgroups_and_ports_neutron_missed(self, vpi_mock):
        vpi_mock.return_value = False
        with task_manager.acquire(self.context, self.node.id) as task:
            free_port_like_objs = (
                common._get_free_portgroups_and_ports(task, self.vif_id,
                                                      {'anyphysnet'}))
        self.assertCountEqual([], free_port_like_objs)

    @mock.patch.object(neutron_common, 'validate_port_info', autospec=True)
    def test__get_free_portgroups_and_ports_neutron(self, vpi_mock):
        vpi_mock.return_value = True
        with task_manager.acquire(self.context, self.node.id) as task:
            free_port_like_objs = (
                common._get_free_portgroups_and_ports(task, self.vif_id,
                                                      {'anyphysnet'}))
        self.assertCountEqual(
            [self.port.uuid], [p.uuid for p in free_port_like_objs])

    @mock.patch.object(neutron_common, 'validate_port_info', autospec=True)
    def test__get_free_portgroups_and_ports_flat(self, vpi_mock):
        self.node.network_interface = 'flat'
        self.node.save()
        vpi_mock.return_value = True
        with task_manager.acquire(self.context, self.node.id) as task:
            free_port_like_objs = (
                common._get_free_portgroups_and_ports(task, self.vif_id,
                                                      {'anyphysnet'}))
        self.assertCountEqual(
            [self.port.uuid], [p.uuid for p in free_port_like_objs])

    def test__get_free_portgroups_and_ports_port_uuid(self):
        self.node.network_interface = 'flat'
        self.node.save()
        pg1, pg1_ports, pg2, pg2_ports, pg3, pg3_ports = self._objects_setup(
            set_physnets=False)
        with task_manager.acquire(self.context, self.node.id) as task:
            free_port_like_objs = (
                common._get_free_portgroups_and_ports(
                    task, self.vif_id, {}, {'port_uuid': self.port.uuid}))
        self.assertCountEqual(
            [self.port.uuid],
            [p.uuid for p in free_port_like_objs])

    def test__get_free_portgroups_and_ports_portgroup_uuid(self):
        self.node.network_interface = 'flat'
        self.node.save()
        pg1, pg1_ports, pg2, pg2_ports, pg3, pg3_ports = self._objects_setup(
            set_physnets=False)
        with task_manager.acquire(self.context, self.node.id) as task:
            free_port_like_objs = (
                common._get_free_portgroups_and_ports(
                    task, self.vif_id, {}, {'portgroup_uuid': pg1.uuid}))
        self.assertCountEqual(
            [pg1.uuid],
            [p.uuid for p in free_port_like_objs])

    def test__get_free_portgroups_and_ports_portgroup_uuid_attached_vifs(self):
        self.node.network_interface = 'flat'
        self.node.save()
        pg1, pg1_ports, pg2, pg2_ports, pg3, pg3_ports = self._objects_setup(
            set_physnets=False)
        with task_manager.acquire(self.context, self.node.id) as task:
            free_port_like_objs = (
                common._get_free_portgroups_and_ports(
                    task, self.vif_id, {}, {'portgroup_uuid': pg2.uuid}))
        self.assertCountEqual(
            [],
            [p.uuid for p in free_port_like_objs])

    def test__get_free_portgroups_and_ports_no_matching_uuid(self):
        self.node.network_interface = 'flat'
        self.node.save()
        pg1, pg1_ports, pg2, pg2_ports, pg3, pg3_ports = self._objects_setup(
            set_physnets=False)
        with task_manager.acquire(self.context, self.node.id) as task:
            free_port_like_objs = (
                common._get_free_portgroups_and_ports(
                    task, self.vif_id, {},
                    {'port_uuid': uuidutils.generate_uuid()}))
        self.assertCountEqual(
            [],
            [p.uuid for p in free_port_like_objs])

    @mock.patch.object(neutron_common, 'validate_port_info', autospec=True,
                       return_value=True)
    def test_get_free_port_like_object_ports(self, vpi_mock):
        with task_manager.acquire(self.context, self.node.id) as task:
            res = common.get_free_port_like_object(task, self.vif_id,
                                                   {'anyphysnet'})
            self.assertEqual(self.port.uuid, res.uuid)

    @mock.patch.object(neutron_common, 'validate_port_info', autospec=True,
                       return_value=True)
    def test_get_free_port_like_object_ports_pxe_enabled_first(self, vpi_mock):
        self.port.pxe_enabled = False
        self.port.save()
        other_port = obj_utils.create_test_port(
            self.context, node_id=self.node.id, address='52:54:00:cf:2d:33',
            uuid=uuidutils.generate_uuid())
        with task_manager.acquire(self.context, self.node.id) as task:
            res = common.get_free_port_like_object(task, self.vif_id,
                                                   {'anyphysnet'})
            self.assertEqual(other_port.uuid, res.uuid)

    @mock.patch.object(neutron_common, 'validate_port_info', autospec=True,
                       return_value=True)
    def test_get_free_port_like_object_ports_physnet_match_first(self,
                                                                 vpi_mock):
        self.port.pxe_enabled = False
        self.port.physical_network = 'physnet1'
        self.port.save()
        obj_utils.create_test_port(
            self.context, node_id=self.node.id, address='52:54:00:cf:2d:33',
            uuid=uuidutils.generate_uuid())
        with task_manager.acquire(self.context, self.node.id) as task:
            res = common.get_free_port_like_object(task, self.vif_id,
                                                   {'physnet1'})
            self.assertEqual(self.port.uuid, res.uuid)

    @mock.patch.object(neutron_common, 'validate_port_info', autospec=True,
                       return_value=True)
    def test_get_free_port_like_object_ports_physnet_match_first2(self,
                                                                  vpi_mock):
        self.port.pxe_enabled = False
        self.port.physical_network = 'physnet1'
        self.port.save()
        pg = obj_utils.create_test_portgroup(
            self.context, node_id=self.node.id)
        obj_utils.create_test_port(
            self.context, node_id=self.node.id, address='52:54:00:cf:2d:01',
            uuid=uuidutils.generate_uuid(), portgroup_id=pg.id)
        with task_manager.acquire(self.context, self.node.id) as task:
            res = common.get_free_port_like_object(task, self.vif_id,
                                                   {'physnet1'})
            self.assertEqual(self.port.uuid, res.uuid)

    @mock.patch.object(neutron_common, 'validate_port_info', autospec=True,
                       return_value=True)
    def test_get_free_port_like_object_portgroup_first(self, vpi_mock):
        pg = obj_utils.create_test_portgroup(
            self.context, node_id=self.node.id)
        obj_utils.create_test_port(
            self.context, node_id=self.node.id, address='52:54:00:cf:2d:01',
            uuid=uuidutils.generate_uuid(), portgroup_id=pg.id)
        with task_manager.acquire(self.context, self.node.id) as task:
            res = common.get_free_port_like_object(task, self.vif_id,
                                                   {'anyphysnet'})
            self.assertEqual(pg.uuid, res.uuid)

    @mock.patch.object(neutron_common, 'validate_port_info', autospec=True,
                       return_value=True)
    def test_get_free_port_like_object_portgroup_physnet_match_first(self,
                                                                     vpi_mock):
        pg1 = obj_utils.create_test_portgroup(
            self.context, node_id=self.node.id)
        obj_utils.create_test_port(
            self.context, node_id=self.node.id, address='52:54:00:cf:2d:01',
            uuid=uuidutils.generate_uuid(), portgroup_id=pg1.id)
        pg2 = obj_utils.create_test_portgroup(
            self.context, node_id=self.node.id, uuid=uuidutils.generate_uuid(),
            name='pg2', address='52:54:00:cf:2d:01')
        obj_utils.create_test_port(
            self.context, node_id=self.node.id, address='52:54:00:cf:2d:02',
            uuid=uuidutils.generate_uuid(), portgroup_id=pg2.id,
            physical_network='physnet1')
        with task_manager.acquire(self.context, self.node.id) as task:
            res = common.get_free_port_like_object(task, self.vif_id,
                                                   {'physnet1'})
            self.assertEqual(pg2.uuid, res.uuid)

    @mock.patch.object(neutron_common, 'validate_port_info', autospec=True,
                       return_value=True)
    def test_get_free_port_like_object_ignores_empty_portgroup(self, vpi_mock):
        obj_utils.create_test_portgroup(self.context, node_id=self.node.id)
        with task_manager.acquire(self.context, self.node.id) as task:
            res = common.get_free_port_like_object(task, self.vif_id,
                                                   {'anyphysnet'})
            self.assertEqual(self.port.uuid, res.uuid)

    @mock.patch.object(neutron_common, 'validate_port_info', autospec=True,
                       return_value=True)
    def test_get_free_port_like_object_ignores_standalone_portgroup(
            self, vpi_mock):
        self.port.destroy()
        pg = obj_utils.create_test_portgroup(
            self.context, node_id=self.node.id)
        obj_utils.create_test_port(
            self.context, node_id=self.node.id, address='52:54:00:cf:2d:01',
            uuid=uuidutils.generate_uuid(), portgroup_id=pg.id,
            internal_info={'tenant_vif_port_id': 'some-vif'})
        free_port = obj_utils.create_test_port(
            self.context, node_id=self.node.id, address='52:54:00:cf:2d:02',
            uuid=uuidutils.generate_uuid(), portgroup_id=pg.id)
        with task_manager.acquire(self.context, self.node.id) as task:
            res = common.get_free_port_like_object(task, self.vif_id,
                                                   {'anyphysnet'})
            self.assertEqual(free_port.uuid, res.uuid)

    @mock.patch.object(neutron_common, 'validate_port_info', autospec=True,
                       return_value=True)
    def test_get_free_port_like_object_vif_attached_to_portgroup(
            self, vpi_mock):
        pg = obj_utils.create_test_portgroup(
            self.context, node_id=self.node.id,
            internal_info={common.TENANT_VIF_KEY: self.vif_id})
        obj_utils.create_test_port(
            self.context, node_id=self.node.id, address='52:54:00:cf:2d:01',
            uuid=uuidutils.generate_uuid(), portgroup_id=pg.id)
        with task_manager.acquire(self.context, self.node.id) as task:
            self.assertRaisesRegex(
                exception.VifAlreadyAttached,
                r"already attached to Ironic Portgroup",
                common.get_free_port_like_object,
                task, self.vif_id, {'anyphysnet'})

    @mock.patch.object(neutron_common, 'validate_port_info', autospec=True,
                       return_value=True)
    def test_get_free_port_like_object_vif_attached_to_port(self, vpi_mock):
        self.port.internal_info = {common.TENANT_VIF_KEY: self.vif_id}
        self.port.save()
        with task_manager.acquire(self.context, self.node.id) as task:
            self.assertRaisesRegex(
                exception.VifAlreadyAttached,
                r"already attached to Ironic Port\b",
                common.get_free_port_like_object,
                task, self.vif_id, {'anyphysnet'})

    @mock.patch.object(neutron_common, 'validate_port_info', autospec=True,
                       return_value=True)
    def test_get_free_port_like_object_nothing_free(self, vpi_mock):
        self.port.internal_info = {'tenant_vif_port_id': 'another-vif'}
        self.port.save()
        with task_manager.acquire(self.context, self.node.id) as task:
            self.assertRaises(exception.NoFreePhysicalPorts,
                              common.get_free_port_like_object,
                              task, self.vif_id, {'anyphysnet'})

    @mock.patch.object(neutron_common, 'validate_port_info', autospec=True,
                       return_value=True)
    def test_get_free_port_like_object_no_matching_physnets(self, vpi_mock):
        self.port.physical_network = 'physnet1'
        self.port.save()
        with task_manager.acquire(self.context, self.node.id) as task:
            self.assertRaises(exception.NoFreePhysicalPorts,
                              common.get_free_port_like_object,
                              task, self.vif_id, {'physnet2'})

    @mock.patch.object(neutron_common, 'update_neutron_port', autospec=True)
    @mock.patch.object(neutron_common, 'get_client', autospec=True)
    def test_plug_port_to_tenant_network_client(self, mock_gc, mock_update):
        self.port.internal_info = {common.TENANT_VIF_KEY: self.vif_id}
        self.port.save()
        with task_manager.acquire(self.context, self.node.id) as task:
            common.plug_port_to_tenant_network(task, self.port,
                                               client=mock.MagicMock())
        self.assertFalse(mock_gc.called)
        self.assertTrue(mock_update.called)

    @mock.patch.object(neutron_common, 'update_neutron_port', autospec=True)
    @mock.patch.object(neutron_common, 'get_client', autospec=True)
    def test_plug_port_to_tenant_network_no_client(self, mock_gc, mock_update):
        self.port.internal_info = {common.TENANT_VIF_KEY: self.vif_id}
        self.port.save()
        with task_manager.acquire(self.context, self.node.id) as task:
            common.plug_port_to_tenant_network(task, self.port)
        self.assertTrue(mock_gc.called)
        self.assertTrue(mock_update.called)

    @mock.patch.object(neutron_common, 'get_client', autospec=True)
    def test_plug_port_to_tenant_network_no_tenant_vif(self, mock_gc):
        nclient = mock.MagicMock()
        mock_gc.return_value = nclient
        self.port.extra = {}
        self.port.save()
        with task_manager.acquire(self.context, self.node.id) as task:
            self.assertRaisesRegex(
                exception.VifNotAttached,
                "not associated with port %s" % self.port.uuid,
                common.plug_port_to_tenant_network,
                task, self.port)

    @mock.patch.object(neutron_common, 'wait_for_host_agent', autospec=True)
    @mock.patch.object(neutron_common, 'wait_for_port_status', autospec=True)
    @mock.patch.object(neutron_common, 'update_neutron_port', autospec=True)
    @mock.patch.object(neutron_common, 'get_client', autospec=True)
    def test_plug_port_to_tenant_network_smartnic_port(
            self, mock_gc, mock_update, wait_port_mock, wait_agent_mock):
        nclient = mock.MagicMock()
        mock_gc.return_value = nclient
        local_link_connection = self.port.local_link_connection
        local_link_connection['hostname'] = 'hostname'
        self.port.local_link_connection = local_link_connection
        self.port.internal_info = {common.TENANT_VIF_KEY: self.vif_id}
        self.port.is_smartnic = True
        self.port.save()
        with task_manager.acquire(self.context, self.node.id) as task:
            common.plug_port_to_tenant_network(task, self.port)
            wait_agent_mock.assert_called_once_with(
                nclient, 'hostname')
            wait_port_mock.assert_called_once_with(
                nclient, self.vif_id, 'ACTIVE')
            self.assertTrue(mock_update.called)


class TestVifPortIDMixin(db_base.DbTestCase):

    def setUp(self):
        super(TestVifPortIDMixin, self).setUp()
        self.interface = common.VIFPortIDMixin()
        self.node = obj_utils.create_test_node(self.context,
                                               network_interface='neutron')
        self.port = obj_utils.create_test_port(
            self.context, node_id=self.node.id,
            address='52:54:00:cf:2d:32',
            internal_info={'tenant_vif_port_id': uuidutils.generate_uuid()},
            extra={'client-id': 'fake1'})
        network_data_file = os.path.join(
            os.path.dirname(__file__), 'json_samples', 'network_data.json')
        with open(network_data_file, 'rb') as fl:
            self.network_data = json.load(fl)

    def test__save_vif_to_port_like_obj_port(self):
        self.port.extra = {}
        self.port.save()
        vif_id = "fake_vif_id"
        self.interface._save_vif_to_port_like_obj(self.port, vif_id)
        self.port.refresh()
        self.assertIn(common.TENANT_VIF_KEY, self.port.internal_info)
        self.assertEqual(vif_id,
                         self.port.internal_info[common.TENANT_VIF_KEY])
        self.assertEqual({}, self.port.extra)

    def test__save_vif_to_port_like_obj_portgroup(self):
        vif_id = "fake_vif_id"
        pg = obj_utils.create_test_portgroup(
            self.context, node_id=self.node.id)
        obj_utils.create_test_port(
            self.context, node_id=self.node.id, address='52:54:00:cf:2d:01',
            portgroup_id=pg.id, uuid=uuidutils.generate_uuid()
        )
        self.interface._save_vif_to_port_like_obj(pg, vif_id)
        pg.refresh()
        self.assertIn(common.TENANT_VIF_KEY, pg.internal_info)
        self.assertEqual(vif_id,
                         pg.internal_info[common.TENANT_VIF_KEY])
        self.assertEqual({}, pg.extra)

    def test__clear_vif_from_port_like_obj_in_extra_port(self):
        self.interface._clear_vif_from_port_like_obj(self.port)
        self.port.refresh()
        self.assertNotIn('vif_port_id', self.port.extra)
        self.assertNotIn(common.TENANT_VIF_KEY, self.port.internal_info)

    def test__clear_vif_from_port_like_obj_in_internal_info_port(self):
        self.port.internal_info = {
            common.TENANT_VIF_KEY: self.port.internal_info[
                'tenant_vif_port_id'
            ]
        }
        self.port.extra = {}
        self.port.save()

        self.interface._clear_vif_from_port_like_obj(self.port)
        self.port.refresh()
        self.assertNotIn('vif_port_id', self.port.extra)
        self.assertNotIn(common.TENANT_VIF_KEY, self.port.internal_info)

    def test__clear_vif_from_port_like_obj_in_extra_portgroup(self):
        vif_id = uuidutils.generate_uuid()
        pg = obj_utils.create_test_portgroup(
            self.context, node_id=self.node.id,
            extra={'vif_port_id': vif_id})
        obj_utils.create_test_port(
            self.context, node_id=self.node.id, address='52:54:00:cf:2d:01',
            portgroup_id=pg.id, uuid=uuidutils.generate_uuid()
        )
        self.interface._clear_vif_from_port_like_obj(pg)
        pg.refresh()
        self.assertNotIn('vif_port_id', pg.extra)
        self.assertNotIn(common.TENANT_VIF_KEY, pg.internal_info)

    def test__clear_vif_from_port_like_obj_in_internal_info_portgroup(self):
        vif_id = uuidutils.generate_uuid()
        pg = obj_utils.create_test_portgroup(
            self.context, node_id=self.node.id,
            internal_info={common.TENANT_VIF_KEY: vif_id})
        obj_utils.create_test_port(
            self.context, node_id=self.node.id, address='52:54:00:cf:2d:01',
            portgroup_id=pg.id, uuid=uuidutils.generate_uuid()
        )
        self.interface._clear_vif_from_port_like_obj(pg)
        pg.refresh()
        self.assertNotIn('vif_port_id', pg.extra)
        self.assertNotIn(common.TENANT_VIF_KEY, pg.internal_info)

    def test__get_port_like_obj_by_vif_id_in_internal_info(self):
        vif_id = self.port.internal_info["tenant_vif_port_id"]
        self.port.internal_info = {common.TENANT_VIF_KEY: vif_id}
        self.port.extra = {}
        self.port.save()
        with task_manager.acquire(self.context, self.node.id) as task:
            result = self.interface._get_port_like_obj_by_vif_id(task, vif_id)
        self.assertEqual(self.port.id, result.id)

    def test__get_port_like_obj_by_vif_id_not_attached(self):
        vif_id = self.port.internal_info["tenant_vif_port_id"]
        self.port.internal_info = {}
        self.port.save()
        with task_manager.acquire(self.context, self.node.id) as task:
            self.assertRaisesRegex(exception.VifNotAttached,
                                   "it is not attached to it.",
                                   self.interface._get_port_like_obj_by_vif_id,
                                   task, vif_id)

    def test__get_vif_id_by_port_like_obj_in_internal_info(self):
        vif_id = self.port.internal_info["tenant_vif_port_id"]
        self.port.internal_info = {common.TENANT_VIF_KEY: vif_id}
        self.port.extra = {}
        self.port.save()
        result = self.interface._get_vif_id_by_port_like_obj(self.port)
        self.assertEqual(vif_id, result)

    def test__get_vif_id_by_port_like_obj_not_attached(self):
        self.port.internal_info = {}
        self.port.save()
        result = self.interface._get_vif_id_by_port_like_obj(self.port)
        self.assertIsNone(result)

    def test_vif_list_port_and_portgroup(self):
        vif_id = uuidutils.generate_uuid()
        self.port.internal_info = {'tenant_vif_port_id': vif_id}
        self.port.save()
        pg_vif_id = uuidutils.generate_uuid()
        portgroup = obj_utils.create_test_portgroup(
            self.context, node_id=self.node.id,
            address='52:54:00:00:00:00',
            internal_info={common.TENANT_VIF_KEY: pg_vif_id})
        obj_utils.create_test_port(
            self.context, node_id=self.node.id, portgroup_id=portgroup.id,
            address='52:54:00:cf:2d:01', uuid=uuidutils.generate_uuid())
        with task_manager.acquire(self.context, self.node.id) as task:
            vifs = self.interface.vif_list(task)
            self.assertCountEqual([{'id': pg_vif_id}, {'id': vif_id}], vifs)

    def test_vif_list_internal(self):
        vif_id = uuidutils.generate_uuid()
        self.port.internal_info = {common.TENANT_VIF_KEY: vif_id}
        self.port.save()
        pg_vif_id = uuidutils.generate_uuid()
        portgroup = obj_utils.create_test_portgroup(
            self.context, node_id=self.node.id,
            address='52:54:00:00:00:00',
            internal_info={common.TENANT_VIF_KEY: pg_vif_id})
        obj_utils.create_test_port(
            self.context, node_id=self.node.id, portgroup_id=portgroup.id,
            address='52:54:00:cf:2d:01', uuid=uuidutils.generate_uuid())
        with task_manager.acquire(self.context, self.node.id) as task:
            vifs = self.interface.vif_list(task)
            self.assertCountEqual([{'id': pg_vif_id}, {'id': vif_id}], vifs)

    def test_vif_list_extra_and_internal_priority(self):
        # TODO(TheJulia): Remove in Xena?
        vif_id = uuidutils.generate_uuid()
        vif_id2 = uuidutils.generate_uuid()
        self.port.extra = {'vif_port_id': vif_id2}
        self.port.internal_info = {common.TENANT_VIF_KEY: vif_id}
        self.port.save()
        with task_manager.acquire(self.context, self.node.id) as task:
            vifs = self.interface.vif_list(task)
            self.assertEqual([{'id': vif_id}], vifs)

    def test_get_current_vif_internal_info_cleaning(self):
        internal_info = {'cleaning_vif_port_id': 'foo',
                         'tenant_vif_port_id': 'bar'}
        self.port.internal_info = internal_info
        self.port.save()
        with task_manager.acquire(self.context, self.node.id) as task:
            vif = self.interface.get_current_vif(task, self.port)
            self.assertEqual('foo', vif)

    def test_get_current_vif_internal_info_provisioning(self):
        internal_info = {'provisioning_vif_port_id': 'foo',
                         'tenant_vif_port_id': 'bar'}
        self.port.internal_info = internal_info
        self.port.save()
        with task_manager.acquire(self.context, self.node.id) as task:
            vif = self.interface.get_current_vif(task, self.port)
            self.assertEqual('foo', vif)

    def test_get_current_vif_internal_info_tenant_vif(self):
        internal_info = {'tenant_vif_port_id': 'bar'}
        self.port.internal_info = internal_info
        self.port.save()
        with task_manager.acquire(self.context, self.node.id) as task:
            vif = self.interface.get_current_vif(task, self.port)
            self.assertEqual('bar', vif)

    def test_get_current_vif_internal_info_rescuing(self):
        internal_info = {'rescuing_vif_port_id': 'foo',
                         'tenant_vif_port_id': 'bar'}
        self.port.internal_info = internal_info
        self.port.save()
        with task_manager.acquire(self.context, self.node.id) as task:
            vif = self.interface.get_current_vif(task, self.port)
            self.assertEqual('foo', vif)

    def test_get_current_vif_none(self):
        internal_info = extra = {}
        self.port.internal_info = internal_info
        self.port.extra = extra
        self.port.save()
        with task_manager.acquire(self.context, self.node.id) as task:
            vif = self.interface.get_current_vif(task, self.port)
            self.assertIsNone(vif)


class TestNeutronVifPortIDMixin(db_base.DbTestCase):

    def setUp(self):
        super(TestNeutronVifPortIDMixin, self).setUp()
        self.interface = common.NeutronVIFPortIDMixin()
        self.node = obj_utils.create_test_node(self.context,
                                               network_interface='neutron')
        self.port = obj_utils.create_test_port(
            self.context, node_id=self.node.id,
            address='52:54:00:cf:2d:32',
            internal_info={'tenant_vif_port_id': uuidutils.generate_uuid()},
            extra={'client-id': 'fake1'})
        self.neutron_port = {'id': '132f871f-eaec-4fed-9475-0d54465e0f00',
                             'mac_address': '52:54:00:cf:2d:32'}

    @mock.patch.object(common.VIFPortIDMixin, '_save_vif_to_port_like_obj',
                       autospec=True)
    @mock.patch.object(common, 'get_free_port_like_object', autospec=True)
    @mock.patch.object(neutron_common, 'get_client', autospec=True)
    @mock.patch.object(neutron_common, 'update_port_address', autospec=True)
    @mock.patch.object(neutron_common, 'get_physnets_by_port_uuid',
                       autospec=True)
    def test_vif_attach(self, mock_gpbpi, mock_upa, mock_client, mock_gfp,
                        mock_save):
        vif = {'id': "fake_vif_id"}
        mock_gfp.return_value = self.port
        with task_manager.acquire(self.context, self.node.id) as task:
            self.interface.vif_attach(task, vif)
            mock_client.assert_called_once_with(context=task.context)
            mock_upa.assert_called_once_with(
                "fake_vif_id", self.port.address, context=task.context)
        self.assertFalse(mock_gpbpi.called)
        mock_gfp.assert_called_once_with(task, 'fake_vif_id', set(),
                                         {'id': 'fake_vif_id'})
        mock_save.assert_called_once_with(self.port, "fake_vif_id")

    @mock.patch.object(common.VIFPortIDMixin, '_save_vif_to_port_like_obj',
                       autospec=True)
    @mock.patch.object(common, 'get_free_port_like_object', autospec=True)
    @mock.patch.object(neutron_common, 'get_client', autospec=True)
    @mock.patch.object(neutron_common, 'update_port_address', autospec=True)
    @mock.patch.object(neutron_common, 'get_physnets_by_port_uuid',
                       autospec=True)
    def test_vif_attach_failure(self, mock_gpbpi, mock_upa, mock_client,
                                mock_gfp, mock_save):
        vif = {'id': "fake_vif_id"}
        mock_gfp.side_effect = exception.NoFreePhysicalPorts(vif='fake-vif')
        with task_manager.acquire(self.context, self.node.id) as task:
            self.assertRaises(exception.NoFreePhysicalPorts,
                              self.interface.vif_attach, task, vif)
        mock_gfp.assert_called_once_with(task, 'fake_vif_id', set(),
                                         {'id': 'fake_vif_id'})
        self.assertFalse(mock_save.called)

    @mock.patch.object(common.VIFPortIDMixin, '_save_vif_to_port_like_obj',
                       autospec=True)
    @mock.patch.object(common, 'get_free_port_like_object', autospec=True)
    @mock.patch.object(neutron_common, 'get_client', autospec=True)
    @mock.patch.object(neutron_common, 'update_port_address', autospec=True)
    @mock.patch.object(neutron_common, 'get_physnets_by_port_uuid',
                       autospec=True)
    def test_vif_attach_with_physnet(self, mock_gpbpi, mock_upa, mock_client,
                                     mock_gfp, mock_save):
        self.port.physical_network = 'physnet1'
        self.port.save()
        vif = {'id': "fake_vif_id"}
        mock_gpbpi.return_value = {'physnet1'}
        mock_gfp.return_value = self.port
        with task_manager.acquire(self.context, self.node.id) as task:
            self.interface.vif_attach(task, vif)
            mock_client.assert_called_once_with(context=task.context)
            mock_upa.assert_called_once_with(
                "fake_vif_id", self.port.address, context=task.context)
        mock_gpbpi.assert_called_once_with(mock_client.return_value,
                                           'fake_vif_id')
        mock_gfp.assert_called_once_with(task, 'fake_vif_id', {'physnet1'},
                                         {'id': 'fake_vif_id'})
        mock_save.assert_called_once_with(self.port, "fake_vif_id")

    @mock.patch.object(common.VIFPortIDMixin, '_save_vif_to_port_like_obj',
                       autospec=True)
    @mock.patch.object(common, 'plug_port_to_tenant_network', autospec=True)
    @mock.patch.object(common, 'get_free_port_like_object', autospec=True)
    @mock.patch.object(neutron_common, 'get_client', autospec=True)
    @mock.patch.object(neutron_common, 'update_port_address', autospec=True)
    @mock.patch.object(neutron_common, 'get_physnets_by_port_uuid',
                       autospec=True)
    def test_vif_attach_active_node(self, mock_gpbpi, mock_upa, mock_client,
                                    mock_gfp, mock_plug, mock_save):
        self.node.provision_state = states.ACTIVE
        self.node.save()
        vif = {'id': "fake_vif_id"}
        mock_gfp.return_value = self.port
        with task_manager.acquire(self.context, self.node.id) as task:
            self.interface.vif_attach(task, vif)
            mock_client.assert_called_once_with(context=task.context)
            mock_upa.assert_called_once_with(
                "fake_vif_id", self.port.address, context=task.context)
        self.assertFalse(mock_gpbpi.called)
        mock_gfp.assert_called_once_with(task, 'fake_vif_id', set(),
                                         {'id': 'fake_vif_id'})
        mock_save.assert_called_once_with(self.port, "fake_vif_id")
        mock_plug.assert_called_once_with(task, self.port, mock.ANY)

    @mock.patch.object(common.VIFPortIDMixin, '_save_vif_to_port_like_obj',
                       autospec=True)
    @mock.patch.object(common, 'plug_port_to_tenant_network', autospec=True)
    @mock.patch.object(common, 'get_free_port_like_object', autospec=True)
    @mock.patch.object(neutron_common, 'get_client', autospec=True)
    @mock.patch.object(neutron_common, 'update_port_address', autospec=True)
    @mock.patch.object(neutron_common, 'get_physnets_by_port_uuid',
                       autospec=True)
    def test_vif_attach_active_node_failure(self, mock_gpbpi, mock_upa,
                                            mock_client, mock_gfp, mock_plug,
                                            mock_save):
        self.node.provision_state = states.ACTIVE
        self.node.save()
        vif = {'id': "fake_vif_id"}
        mock_gfp.return_value = self.port
        mock_plug.side_effect = exception.NetworkError
        with task_manager.acquire(self.context, self.node.id) as task:
            self.assertRaises(exception.NetworkError,
                              self.interface.vif_attach, task, vif)
            mock_client.assert_called_once_with(context=task.context)
            mock_upa.assert_called_once_with(
                "fake_vif_id", self.port.address, context=task.context)
        self.assertFalse(mock_gpbpi.called)
        mock_gfp.assert_called_once_with(task, 'fake_vif_id', set(),
                                         {'id': 'fake_vif_id'})
        mock_save.assert_called_once_with(self.port, "fake_vif_id")
        mock_plug.assert_called_once_with(task, self.port, mock.ANY)

    @mock.patch.object(common.VIFPortIDMixin, '_save_vif_to_port_like_obj',
                       autospec=True)
    @mock.patch.object(common, 'get_free_port_like_object', autospec=True)
    @mock.patch.object(neutron_common, 'get_client', autospec=True)
    @mock.patch.object(neutron_common, 'update_port_address', autospec=True)
    @mock.patch.object(neutron_common, 'get_physnets_by_port_uuid',
                       autospec=True)
    def test_vif_attach_portgroup_no_address(self, mock_gpbpi, mock_upa,
                                             mock_client, mock_gfp, mock_save):
        pg = obj_utils.create_test_portgroup(
            self.context, node_id=self.node.id, address=None)
        mock_gfp.return_value = pg
        vif = {'id': "fake_vif_id"}
        with task_manager.acquire(self.context, self.node.id) as task:
            self.interface.vif_attach(task, vif)
            mock_client.assert_called_once_with(context=task.context)
        self.assertFalse(mock_gpbpi.called)
        mock_gfp.assert_called_once_with(task, 'fake_vif_id', set(),
                                         {'id': 'fake_vif_id'})
        self.assertFalse(mock_client.return_value.show_port.called)
        self.assertFalse(mock_upa.called)
        mock_save.assert_called_once_with(pg, "fake_vif_id")

    @mock.patch.object(common.VIFPortIDMixin, '_save_vif_to_port_like_obj',
                       autospec=True)
    @mock.patch.object(neutron_common, 'get_client', autospec=True)
    @mock.patch.object(neutron_common, 'update_port_address', autospec=True)
    @mock.patch.object(neutron_common, 'get_physnets_by_port_uuid',
                       autospec=True)
    def test_vif_attach_update_port_exception(self, mock_gpbpi, mock_upa,
                                              mock_client, mock_save):
        self.port.internal_info = {}
        self.port.physical_network = 'physnet1'
        self.port.save()
        vif = {'id': "fake_vif_id"}
        mock_gpbpi.return_value = {'physnet1'}
        mock_upa.side_effect = (
            exception.FailedToUpdateMacOnPort(port_id='fake'))
        with task_manager.acquire(self.context, self.node.id) as task:
            self.assertRaisesRegex(
                exception.NetworkError, "can not update Neutron port",
                self.interface.vif_attach, task, vif)
            mock_client.assert_called_once_with(context=task.context)
        mock_gpbpi.assert_called_once_with(mock_client.return_value,
                                           'fake_vif_id')
        self.assertFalse(mock_save.called)

    @mock.patch.object(common.VIFPortIDMixin, '_save_vif_to_port_like_obj',
                       autospec=True)
    @mock.patch.object(common, 'get_free_port_like_object', autospec=True)
    @mock.patch.object(neutron_common, 'get_client', autospec=True)
    @mock.patch.object(neutron_common, 'update_port_address', autospec=True)
    @mock.patch.object(neutron_common, 'get_physnets_by_port_uuid',
                       autospec=True)
    def test_vif_attach_portgroup_physnet_inconsistent(self, mock_gpbpi,
                                                       mock_upa, mock_client,
                                                       mock_gfp, mock_save):
        self.port.physical_network = 'physnet1'
        self.port.save()
        vif = {'id': "fake_vif_id"}
        mock_gpbpi.return_value = {'anyphysnet'}
        mock_gfp.side_effect = exception.PortgroupPhysnetInconsistent(
            portgroup='fake-portgroup-id', physical_networks='physnet1')
        with task_manager.acquire(self.context, self.node.id) as task:
            self.assertRaises(
                exception.PortgroupPhysnetInconsistent,
                self.interface.vif_attach, task, vif)
            mock_client.assert_called_once_with(context=task.context)
        mock_gpbpi.assert_called_once_with(mock_client.return_value,
                                           'fake_vif_id')
        self.assertFalse(mock_upa.called)
        self.assertFalse(mock_save.called)

    @mock.patch.object(common.VIFPortIDMixin, '_save_vif_to_port_like_obj',
                       autospec=True)
    @mock.patch.object(common, 'get_free_port_like_object', autospec=True)
    @mock.patch.object(neutron_common, 'get_client', autospec=True)
    @mock.patch.object(neutron_common, 'update_port_address', autospec=True)
    @mock.patch.object(neutron_common, 'get_physnets_by_port_uuid',
                       autospec=True)
    def test_vif_attach_multiple_segment_mappings(self, mock_gpbpi, mock_upa,
                                                  mock_client, mock_gfp,
                                                  mock_save):
        self.port.physical_network = 'physnet1'
        self.port.save()
        obj_utils.create_test_port(
            self.context, node_id=self.node.id, uuid=uuidutils.generate_uuid(),
            address='52:54:00:cf:2d:33', physical_network='physnet2')
        vif = {'id': "fake_vif_id"}
        mock_gpbpi.return_value = {'physnet1', 'physnet2'}
        with task_manager.acquire(self.context, self.node.id) as task:
            self.assertRaises(
                exception.VifInvalidForAttach,
                self.interface.vif_attach, task, vif)
            mock_client.assert_called_once_with(context=task.context)
        mock_gpbpi.assert_called_once_with(mock_client.return_value,
                                           'fake_vif_id')
        self.assertFalse(mock_gfp.called)
        self.assertFalse(mock_upa.called)
        self.assertFalse(mock_save.called)

    @mock.patch.object(common.VIFPortIDMixin, '_clear_vif_from_port_like_obj',
                       autospec=True)
    @mock.patch.object(neutron_common, 'unbind_neutron_port', autospec=True)
    @mock.patch.object(common.VIFPortIDMixin, '_get_port_like_obj_by_vif_id',
                       autospec=True)
    def test_vif_detach(self, mock_get, mock_unp, mock_clear):
        mock_get.return_value = self.port
        with task_manager.acquire(self.context, self.node.id) as task:
            self.interface.vif_detach(task, 'fake_vif_id')
        mock_get.assert_called_once_with(self.interface, task, 'fake_vif_id')
        self.assertFalse(mock_unp.called)
        mock_clear.assert_called_once_with(self.port)

    @mock.patch.object(common.VIFPortIDMixin, '_clear_vif_from_port_like_obj',
                       autospec=True)
    @mock.patch.object(neutron_common, 'unbind_neutron_port', autospec=True)
    @mock.patch.object(common.VIFPortIDMixin, '_get_port_like_obj_by_vif_id',
                       autospec=True)
    def test_vif_detach_portgroup(self, mock_get, mock_unp, mock_clear):
        pg = obj_utils.create_test_portgroup(
            self.context, node_id=self.node.id)
        mock_get.return_value = pg
        with task_manager.acquire(self.context, self.node.id) as task:
            self.interface.vif_detach(task, 'fake_vif_id')
        mock_get.assert_called_once_with(self.interface, task, 'fake_vif_id')
        self.assertFalse(mock_unp.called)
        mock_clear.assert_called_once_with(pg)

    @mock.patch.object(common.VIFPortIDMixin, '_clear_vif_from_port_like_obj',
                       autospec=True)
    @mock.patch.object(neutron_common, 'unbind_neutron_port', autospec=True)
    @mock.patch.object(common.VIFPortIDMixin, '_get_port_like_obj_by_vif_id',
                       autospec=True)
    def test_vif_detach_not_attached(self, mock_get, mock_unp, mock_clear):
        mock_get.side_effect = exception.VifNotAttached(vif='fake-vif',
                                                        node='fake-node')
        with task_manager.acquire(self.context, self.node.id) as task:
            self.assertRaisesRegex(
                exception.VifNotAttached, "it is not attached to it.",
                self.interface.vif_detach, task, 'fake_vif_id')
        mock_get.assert_called_once_with(self.interface, task, 'fake_vif_id')
        self.assertFalse(mock_unp.called)
        self.assertFalse(mock_clear.called)

    @mock.patch.object(common.VIFPortIDMixin, '_clear_vif_from_port_like_obj',
                       autospec=True)
    @mock.patch.object(neutron_common, 'unbind_neutron_port', autospec=True)
    @mock.patch.object(common.VIFPortIDMixin, '_get_port_like_obj_by_vif_id',
                       autospec=True)
    def test_vif_detach_active_node(self, mock_get, mock_unp, mock_clear):
        self.node.provision_state = states.ACTIVE
        self.node.save()
        mock_get.return_value = self.port
        with task_manager.acquire(self.context, self.node.id) as task:
            self.interface.vif_detach(task, 'fake_vif_id')
            mock_unp.assert_called_once_with('fake_vif_id',
                                             context=task.context)
        mock_get.assert_called_once_with(self.interface, task, 'fake_vif_id')
        mock_clear.assert_called_once_with(self.port)

    @mock.patch.object(common.VIFPortIDMixin, '_clear_vif_from_port_like_obj',
                       autospec=True)
    @mock.patch.object(neutron_common, 'unbind_neutron_port', autospec=True)
    @mock.patch.object(common.VIFPortIDMixin, '_get_port_like_obj_by_vif_id',
                       autospec=True)
    def test_vif_detach_deleting_node(self, mock_get, mock_unp, mock_clear):
        self.node.provision_state = states.DELETING
        self.node.save()
        mock_get.return_value = self.port
        with task_manager.acquire(self.context, self.node.id) as task:
            self.interface.vif_detach(task, 'fake_vif_id')
            mock_unp.assert_called_once_with('fake_vif_id',
                                             context=task.context)
        mock_get.assert_called_once_with(self.interface, task, 'fake_vif_id')
        mock_clear.assert_called_once_with(self.port)

    @mock.patch.object(common.VIFPortIDMixin, '_clear_vif_from_port_like_obj',
                       autospec=True)
    @mock.patch.object(neutron_common, 'unbind_neutron_port', autospec=True)
    @mock.patch.object(common.VIFPortIDMixin, '_get_port_like_obj_by_vif_id',
                       autospec=True)
    def test_vif_detach_active_node_failure(self, mock_get, mock_unp,
                                            mock_clear):
        self.node.provision_state = states.ACTIVE
        self.node.save()
        mock_get.return_value = self.port
        mock_unp.side_effect = exception.NetworkError
        with task_manager.acquire(self.context, self.node.id) as task:
            self.assertRaises(exception.NetworkError,
                              self.interface.vif_detach, task, 'fake_vif_id')
            mock_unp.assert_called_once_with('fake_vif_id',
                                             context=task.context)
        mock_get.assert_called_once_with(self.interface, task, 'fake_vif_id')
        mock_clear.assert_called_once_with(self.port)

    @mock.patch.object(neutron_common, 'update_port_address', autospec=True)
    def test_port_changed_address(self, mac_update_mock):
        new_address = '11:22:33:44:55:bb'
        self.port.address = new_address
        with task_manager.acquire(self.context, self.node.id) as task:
            self.interface.port_changed(task, self.port)
            mac_update_mock.assert_called_once_with(
                self.port.internal_info['tenant_vif_port_id'],
                new_address,
                context=task.context)

    @mock.patch.object(neutron_common, 'update_port_address', autospec=True)
    def test_port_changed_address_VIF_MAC_update_fail(self, mac_update_mock):
        new_address = '11:22:33:44:55:bb'
        self.port.address = new_address
        mac_update_mock.side_effect = (
            exception.FailedToUpdateMacOnPort(port_id=self.port.uuid))
        with task_manager.acquire(self.context, self.node.id) as task:
            self.assertRaises(exception.FailedToUpdateMacOnPort,
                              self.interface.port_changed,
                              task, self.port)
            mac_update_mock.assert_called_once_with(
                self.port.internal_info['tenant_vif_port_id'], new_address,
                context=task.context)

    @mock.patch.object(neutron_common, 'update_port_address', autospec=True)
    def test_port_changed_address_no_vif_id(self, mac_update_mock):
        self.port.internal_info = {}
        self.port.save()
        self.port.address = '11:22:33:44:55:bb'
        with task_manager.acquire(self.context, self.node.id) as task:
            self.interface.port_changed(task, self.port)
            self.assertFalse(mac_update_mock.called)

    @mock.patch('ironic.dhcp.neutron.NeutronDHCPApi.update_port_dhcp_opts',
                autospec=True)
    def test_port_changed_client_id(self, dhcp_update_mock):
        expected_ii = {'tenant_vif_port_id': 'fake-id'}
        expected_extra = {'client-id': 'fake2'}
        expected_dhcp_opts = [{'opt_name': '61', 'opt_value': 'fake2'}]
        self.port.extra = expected_extra
        self.port.internal_info = expected_ii
        with task_manager.acquire(self.context, self.node.id) as task:
            self.interface.port_changed(task, self.port)
            dhcp_update_mock.assert_called_once_with(
                mock.ANY, 'fake-id', expected_dhcp_opts, context=task.context)

    @mock.patch('ironic.dhcp.neutron.NeutronDHCPApi.update_port_dhcp_opts',
                autospec=True)
    def test_port_changed_extra_add_new_key(self, dhcp_update_mock):
        self.port.internal_info = {'tenant_vif_port_id': 'fake-id'}
        self.port.save()
        expected_extra = self.port.extra
        expected_extra['foo'] = 'bar'
        self.port.extra = expected_extra
        with task_manager.acquire(self.context, self.node.id) as task:
            self.interface.port_changed(task, self.port)
            self.assertFalse(dhcp_update_mock.called)

    @mock.patch('ironic.dhcp.neutron.NeutronDHCPApi.update_port_dhcp_opts',
                autospec=True)
    def test_port_changed_client_id_fail(self, dhcp_update_mock):
        self.port.internal_info = {'tenant_vif_port_id': 'fake-id'}
        self.port.extra = {'client-id': 'fake3'}
        what_changed_mock = mock.Mock()
        what_changed_mock.return_value = ['extra']
        self.port.obj_what_changed = what_changed_mock
        dhcp_update_mock.side_effect = (
            exception.FailedToUpdateDHCPOptOnPort(port_id=self.port.uuid))
        with task_manager.acquire(self.context, self.node.id) as task:
            self.assertRaises(exception.FailedToUpdateDHCPOptOnPort,
                              self.interface.port_changed,
                              task, self.port)
        self.assertEqual(2, what_changed_mock.call_count)

    @mock.patch('ironic.dhcp.neutron.NeutronDHCPApi.update_port_dhcp_opts',
                autospec=True)
    def test_port_changed_client_id_no_vif_id(self, dhcp_update_mock):
        self.port.internal_info = {}
        self.port.extra = {'client-id': 'fake1'}
        self.port.save()
        self.port.extra = {'client-id': 'fake2'}
        with task_manager.acquire(self.context, self.node.id) as task:
            self.interface.port_changed(task, self.port)
            self.assertFalse(dhcp_update_mock.called)

    @mock.patch('ironic.dhcp.neutron.NeutronDHCPApi.update_port_dhcp_opts',
                autospec=True)
    def test_port_changed_message_format_failure(self, dhcp_update_mock):
        pg = obj_utils.create_test_portgroup(
            self.context, node_id=self.node.id,
            standalone_ports_supported=False)

        port = obj_utils.create_test_port(
            self.context, node_id=self.node.id,
            uuid=uuidutils.generate_uuid(),
            address="aa:bb:cc:dd:ee:01",
            internal_info={'tenant_vif_port_id': 'blah'},
            pxe_enabled=False)
        port.portgroup_id = pg.id

        with task_manager.acquire(self.context, self.node.id) as task:
            self.assertRaisesRegex(exception.Conflict,
                                   "VIF blah is attached to the port",
                                   self.interface.port_changed,
                                   task, port)

    def _test_port_changed(self, has_vif=False, in_portgroup=False,
                           pxe_enabled=True, standalone_ports=True,
                           expect_errors=False):
        pg = obj_utils.create_test_portgroup(
            self.context, node_id=self.node.id,
            standalone_ports_supported=standalone_ports)

        extra_vif = {'tenant_vif_port_id': uuidutils.generate_uuid()}
        if has_vif:
            internal_info = extra_vif
            opposite_extra = {}
        else:
            internal_info = {}
            opposite_extra = extra_vif
        opposite_pxe_enabled = not pxe_enabled

        pg_id = None
        if in_portgroup:
            pg_id = pg.id

        ports = []

        # Update only portgroup id on existed port with different
        # combinations of pxe_enabled/vif_port_id
        p1 = obj_utils.create_test_port(self.context, node_id=self.node.id,
                                        uuid=uuidutils.generate_uuid(),
                                        address="aa:bb:cc:dd:ee:01",
                                        internal_info=internal_info,
                                        pxe_enabled=pxe_enabled)
        p1.portgroup_id = pg_id
        ports.append(p1)

        # Update portgroup_id/pxe_enabled/vif_port_id in one request
        p2 = obj_utils.create_test_port(self.context, node_id=self.node.id,
                                        uuid=uuidutils.generate_uuid(),
                                        address="aa:bb:cc:dd:ee:02",
                                        internal_info=opposite_extra,
                                        pxe_enabled=opposite_pxe_enabled)
        p2.internal_info = internal_info
        p2.pxe_enabled = pxe_enabled
        p2.portgroup_id = pg_id
        ports.append(p2)

        # Update portgroup_id and pxe_enabled
        p3 = obj_utils.create_test_port(self.context, node_id=self.node.id,
                                        uuid=uuidutils.generate_uuid(),
                                        address="aa:bb:cc:dd:ee:03",
                                        internal_info=internal_info,
                                        pxe_enabled=opposite_pxe_enabled)
        p3.pxe_enabled = pxe_enabled
        p3.portgroup_id = pg_id
        ports.append(p3)

        # Update portgroup_id and vif_port_id
        p4 = obj_utils.create_test_port(self.context, node_id=self.node.id,
                                        uuid=uuidutils.generate_uuid(),
                                        address="aa:bb:cc:dd:ee:04",
                                        pxe_enabled=pxe_enabled,
                                        internal_info=opposite_extra)
        p4.internal_info = internal_info
        p4.portgroup_id = pg_id
        ports.append(p4)

        for port in ports:
            with task_manager.acquire(self.context, self.node.id) as task:
                if not expect_errors:
                    self.interface.port_changed(task, port)
                else:
                    self.assertRaises(exception.Conflict,
                                      self.interface.port_changed,
                                      task, port)

    def test_port_changed_novif_pxe_noportgroup(self):
        self._test_port_changed(has_vif=False, in_portgroup=False,
                                pxe_enabled=True,
                                expect_errors=False)

    def test_port_changed_novif_nopxe_noportgroup(self):
        self._test_port_changed(has_vif=False, in_portgroup=False,
                                pxe_enabled=False,
                                expect_errors=False)

    def test_port_changed_vif_pxe_noportgroup(self):
        self._test_port_changed(has_vif=True, in_portgroup=False,
                                pxe_enabled=True,
                                expect_errors=False)

    def test_port_changed_vif_nopxe_noportgroup(self):
        self._test_port_changed(has_vif=True, in_portgroup=False,
                                pxe_enabled=False,
                                expect_errors=False)

    def test_port_changed_novif_pxe_portgroup_standalone_ports(self):
        self._test_port_changed(has_vif=False, in_portgroup=True,
                                pxe_enabled=True, standalone_ports=True,
                                expect_errors=False)

    def test_port_changed_novif_pxe_portgroup_nostandalone_ports(self):
        self._test_port_changed(has_vif=False, in_portgroup=True,
                                pxe_enabled=True, standalone_ports=False,
                                expect_errors=True)

    def test_port_changed_novif_nopxe_portgroup_standalone_ports(self):
        self._test_port_changed(has_vif=False, in_portgroup=True,
                                pxe_enabled=False, standalone_ports=True,
                                expect_errors=False)

    def test_port_changed_novif_nopxe_portgroup_nostandalone_ports(self):
        self._test_port_changed(has_vif=False, in_portgroup=True,
                                pxe_enabled=False, standalone_ports=False,
                                expect_errors=False)

    def test_port_changed_vif_pxe_portgroup_standalone_ports(self):
        self._test_port_changed(has_vif=True, in_portgroup=True,
                                pxe_enabled=True, standalone_ports=True,
                                expect_errors=False)

    def test_port_changed_vif_pxe_portgroup_nostandalone_ports(self):
        self._test_port_changed(has_vif=True, in_portgroup=True,
                                pxe_enabled=True, standalone_ports=False,
                                expect_errors=True)

    def test_port_changed_vif_nopxe_portgroup_standalone_ports(self):
        self._test_port_changed(has_vif=True, in_portgroup=True,
                                pxe_enabled=True, standalone_ports=True,
                                expect_errors=False)

    def test_port_changed_vif_nopxe_portgroup_nostandalone_ports(self):
        self._test_port_changed(has_vif=True, in_portgroup=True,
                                pxe_enabled=False, standalone_ports=False,
                                expect_errors=True)

    @mock.patch.object(neutron_common, 'update_port_address', autospec=True)
    def test_update_portgroup_address(self, mac_update_mock):
        pg = obj_utils.create_test_portgroup(
            self.context, node_id=self.node.id,
            internal_info={'tenant_vif_port_id': 'fake-id'})
        new_address = '11:22:33:44:55:bb'
        pg.address = new_address
        with task_manager.acquire(self.context, self.node.id) as task:
            self.interface.portgroup_changed(task, pg)
            mac_update_mock.assert_called_once_with(
                'fake-id', new_address, context=task.context)

    @mock.patch.object(neutron_common, 'update_port_address', autospec=True)
    def test_update_portgroup_remove_address(self, mac_update_mock):
        pg = obj_utils.create_test_portgroup(
            self.context, node_id=self.node.id,
            internal_info={'tenant_vif_port_id': 'fake-id'})
        pg.address = None
        with task_manager.acquire(self.context, self.node.id) as task:
            self.interface.portgroup_changed(task, pg)
        self.assertFalse(mac_update_mock.called)

    @mock.patch.object(neutron_common, 'update_port_address', autospec=True)
    def test_update_portgroup_address_fail(self, mac_update_mock):
        pg = obj_utils.create_test_portgroup(
            self.context, node_id=self.node.id,
            internal_info={'tenant_vif_port_id': 'fake-id'})
        new_address = '11:22:33:44:55:bb'
        pg.address = new_address
        mac_update_mock.side_effect = (
            exception.FailedToUpdateMacOnPort('boom'))
        with task_manager.acquire(self.context, self.node.id) as task:
            self.assertRaises(exception.FailedToUpdateMacOnPort,
                              self.interface.portgroup_changed,
                              task, pg)
            mac_update_mock.assert_called_once_with(
                'fake-id', new_address, context=task.context)

    @mock.patch.object(neutron_common, 'update_port_address', autospec=True)
    def test_update_portgroup_address_no_vif(self, mac_update_mock):
        pg = obj_utils.create_test_portgroup(
            self.context, node_id=self.node.id)
        new_address = '11:22:33:44:55:bb'
        pg.address = new_address
        with task_manager.acquire(self.context, self.node.id) as task:
            self.interface.portgroup_changed(task, pg)
        self.assertEqual(new_address, pg.address)
        self.assertFalse(mac_update_mock.called)

    @mock.patch.object(neutron_common, 'update_port_address', autospec=True)
    def test_update_portgroup_nostandalone_ports_pxe_ports_exc(
            self, mac_update_mock):
        pg = obj_utils.create_test_portgroup(
            self.context, node_id=self.node.id)
        internal_info = {'tenant_vif_port_id': 'foo'}
        obj_utils.create_test_port(
            self.context, node_id=self.node.id,
            internal_info=internal_info,
            pxe_enabled=True, portgroup_id=pg.id,
            address="aa:bb:cc:dd:ee:01",
            uuid=uuidutils.generate_uuid())

        pg.standalone_ports_supported = False
        with task_manager.acquire(self.context, self.node.id) as task:
            self.assertRaisesRegex(exception.Conflict,
                                   "VIF foo is attached to this port",
                                   self.interface.portgroup_changed,
                                   task, pg)

    def _test_update_portgroup(self, has_vif=False, with_ports=False,
                               pxe_enabled=True, standalone_ports=True,
                               expect_errors=False):
        # NOTE(vsaienko) make sure that old values are opposite to new,
        # to guarantee that object.what_changes() returns true.
        old_standalone_ports_supported = not standalone_ports

        pg = obj_utils.create_test_portgroup(
            self.context, node_id=self.node.id,
            standalone_ports_supported=old_standalone_ports_supported)

        if with_ports:
            internal_info = {}
            if has_vif:
                internal_info = {
                    'tenant_vif_port_id': uuidutils.generate_uuid()
                }

            obj_utils.create_test_port(
                self.context, node_id=self.node.id,
                internal_info=internal_info,
                pxe_enabled=pxe_enabled, portgroup_id=pg.id,
                address="aa:bb:cc:dd:ee:01",
                uuid=uuidutils.generate_uuid())

        pg.standalone_ports_supported = standalone_ports

        with task_manager.acquire(self.context, self.node.id) as task:
            if not expect_errors:
                self.interface.portgroup_changed(task, pg)
            else:
                self.assertRaises(exception.Conflict,
                                  self.interface.portgroup_changed,
                                  task, pg)

    def test_update_portgroup_standalone_ports_noports(self):
        self._test_update_portgroup(with_ports=False, standalone_ports=True,
                                    expect_errors=False)

    def test_update_portgroup_standalone_ports_novif_pxe_ports(self):
        self._test_update_portgroup(with_ports=True, standalone_ports=True,
                                    has_vif=False, pxe_enabled=True,
                                    expect_errors=False)

    def test_update_portgroup_nostandalone_ports_novif_pxe_ports(self):
        self._test_update_portgroup(with_ports=True, standalone_ports=False,
                                    has_vif=False, pxe_enabled=True,
                                    expect_errors=True)

    def test_update_portgroup_nostandalone_ports_novif_nopxe_ports(self):
        self._test_update_portgroup(with_ports=True, standalone_ports=False,
                                    has_vif=False, pxe_enabled=False,
                                    expect_errors=False)

    def test_update_portgroup_standalone_ports_novif_nopxe_ports(self):
        self._test_update_portgroup(with_ports=True, standalone_ports=True,
                                    has_vif=False, pxe_enabled=False,
                                    expect_errors=False)

    def test_update_portgroup_standalone_ports_vif_pxe_ports(self):
        self._test_update_portgroup(with_ports=True, standalone_ports=True,
                                    has_vif=True, pxe_enabled=True,
                                    expect_errors=False)

    def test_update_portgroup_nostandalone_ports_vif_pxe_ports(self):
        self._test_update_portgroup(with_ports=True, standalone_ports=False,
                                    has_vif=True, pxe_enabled=True,
                                    expect_errors=True)

    def test_update_portgroup_standalone_ports_vif_nopxe_ports(self):
        self._test_update_portgroup(with_ports=True, standalone_ports=True,
                                    has_vif=True, pxe_enabled=False,
                                    expect_errors=False)

    def test_update_portgroup_nostandalone_ports_vif_nopxe_ports(self):
        self._test_update_portgroup(with_ports=True, standalone_ports=False,
                                    has_vif=True, pxe_enabled=False,
                                    expect_errors=True)
