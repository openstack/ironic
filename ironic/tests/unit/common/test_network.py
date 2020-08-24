# Copyright 2014 Rackspace Inc.
# All Rights Reserved
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

from unittest import mock

from oslo_utils import uuidutils

from ironic.common import exception
from ironic.common import network
from ironic.common import neutron as neutron_common
from ironic.common import states
from ironic.conductor import task_manager
from ironic.drivers.modules.network import common as driver_common
from ironic.tests.unit.db import base as db_base
from ironic.tests.unit.db import utils as db_utils
from ironic.tests.unit.objects import utils as object_utils


class TestNetwork(db_base.DbTestCase):

    def setUp(self):
        super(TestNetwork, self).setUp()
        self.node = object_utils.create_test_node(self.context)

    def test_get_node_vif_ids_no_ports_no_portgroups(self):
        expected = {'portgroups': {},
                    'ports': {}}
        with task_manager.acquire(self.context, self.node.uuid) as task:
            result = network.get_node_vif_ids(task)
        self.assertEqual(expected, result)

    def _test_get_node_vif_ids_one_port(self, key):
        if key == "extra":
            kwargs1 = {key: {'vif_port_id': 'test-vif-A'}}
        else:
            kwargs1 = {key: {'tenant_vif_port_id': 'test-vif-A'}}
        port1 = db_utils.create_test_port(node_id=self.node.id,
                                          address='aa:bb:cc:dd:ee:ff',
                                          uuid=uuidutils.generate_uuid(),
                                          **kwargs1)
        expected = {'portgroups': {},
                    'ports': {port1.uuid: 'test-vif-A'}}
        with task_manager.acquire(self.context, self.node.uuid) as task:
            result = network.get_node_vif_ids(task)
        self.assertEqual(expected, result)

    def test_get_node_vif_ids_one_port_extra(self):
        self._test_get_node_vif_ids_one_port("extra")

    def test_get_node_vif_ids_one_port_int_info(self):
        self._test_get_node_vif_ids_one_port("internal_info")

    def _test_get_node_vif_ids_one_portgroup(self, key):
        if key == "extra":
            kwargs1 = {key: {'vif_port_id': 'test-vif-A'}}
        else:
            kwargs1 = {key: {'tenant_vif_port_id': 'test-vif-A'}}
        pg1 = db_utils.create_test_portgroup(
            node_id=self.node.id, **kwargs1)

        expected = {'portgroups': {pg1.uuid: 'test-vif-A'},
                    'ports': {}}
        with task_manager.acquire(self.context, self.node.uuid) as task:
            result = network.get_node_vif_ids(task)
        self.assertEqual(expected, result)

    def test_get_node_vif_ids_one_portgroup_extra(self):
        self._test_get_node_vif_ids_one_portgroup("extra")

    def test_get_node_vif_ids_one_portgroup_int_info(self):
        self._test_get_node_vif_ids_one_portgroup("internal_info")

    def _test_get_node_vif_ids_two_ports(self, key):
        if key == "extra":
            kwargs1 = {key: {'vif_port_id': 'test-vif-A'}}
            kwargs2 = {key: {'vif_port_id': 'test-vif-B'}}
        else:
            kwargs1 = {key: {'tenant_vif_port_id': 'test-vif-A'}}
            kwargs2 = {key: {'tenant_vif_port_id': 'test-vif-B'}}
        port1 = db_utils.create_test_port(node_id=self.node.id,
                                          address='aa:bb:cc:dd:ee:ff',
                                          uuid=uuidutils.generate_uuid(),
                                          **kwargs1)
        port2 = db_utils.create_test_port(node_id=self.node.id,
                                          address='dd:ee:ff:aa:bb:cc',
                                          uuid=uuidutils.generate_uuid(),
                                          **kwargs2)
        expected = {'portgroups': {},
                    'ports': {port1.uuid: 'test-vif-A',
                              port2.uuid: 'test-vif-B'}}
        with task_manager.acquire(self.context, self.node.uuid) as task:
            result = network.get_node_vif_ids(task)
        self.assertEqual(expected, result)

    def test_get_node_vif_ids_two_ports_extra(self):
        self._test_get_node_vif_ids_two_ports('extra')

    def test_get_node_vif_ids_two_ports_int_info(self):
        self._test_get_node_vif_ids_two_ports('internal_info')

    def _test_get_node_vif_ids_two_portgroups(self, key):
        if key == "extra":
            kwargs1 = {key: {'vif_port_id': 'test-vif-A'}}
            kwargs2 = {key: {'vif_port_id': 'test-vif-B'}}
        else:
            kwargs1 = {key: {'tenant_vif_port_id': 'test-vif-A'}}
            kwargs2 = {key: {'tenant_vif_port_id': 'test-vif-B'}}
        pg1 = db_utils.create_test_portgroup(
            node_id=self.node.id, **kwargs1)
        pg2 = db_utils.create_test_portgroup(
            uuid=uuidutils.generate_uuid(),
            address='dd:ee:ff:aa:bb:cc',
            node_id=self.node.id,
            name='barname', **kwargs2)
        expected = {'portgroups': {pg1.uuid: 'test-vif-A',
                                   pg2.uuid: 'test-vif-B'},
                    'ports': {}}
        with task_manager.acquire(self.context, self.node.uuid) as task:
            result = network.get_node_vif_ids(task)
        self.assertEqual(expected, result)

    def test_get_node_vif_ids_two_portgroups_extra(self):
        self._test_get_node_vif_ids_two_portgroups('extra')

    def test_get_node_vif_ids_two_portgroups_int_info(self):
        self._test_get_node_vif_ids_two_portgroups('internal_info')

    def _test_get_node_vif_ids_multitenancy(self, int_info_key):
        port = db_utils.create_test_port(
            node_id=self.node.id, address='aa:bb:cc:dd:ee:ff',
            internal_info={int_info_key: 'test-vif-A'})
        portgroup = db_utils.create_test_portgroup(
            node_id=self.node.id, address='dd:ee:ff:aa:bb:cc',
            internal_info={int_info_key: 'test-vif-B'})
        expected = {'ports': {port.uuid: 'test-vif-A'},
                    'portgroups': {portgroup.uuid: 'test-vif-B'}}
        with task_manager.acquire(self.context, self.node.uuid) as task:
            result = network.get_node_vif_ids(task)
        self.assertEqual(expected, result)

    def test_get_node_vif_ids_during_cleaning(self):
        self._test_get_node_vif_ids_multitenancy('cleaning_vif_port_id')

    def test_get_node_vif_ids_during_provisioning(self):
        self._test_get_node_vif_ids_multitenancy('provisioning_vif_port_id')

    def test_get_node_vif_ids_during_rescuing(self):
        self._test_get_node_vif_ids_multitenancy('rescuing_vif_port_id')

    def test_remove_vifs_from_node(self):
        db_utils.create_test_port(
            node_id=self.node.id, address='aa:bb:cc:dd:ee:ff',
            internal_info={driver_common.TENANT_VIF_KEY: 'test-vif-A'})
        db_utils.create_test_portgroup(
            node_id=self.node.id, address='dd:ee:ff:aa:bb:cc',
            internal_info={driver_common.TENANT_VIF_KEY: 'test-vif-B'})
        with task_manager.acquire(self.context, self.node.uuid) as task:
            network.remove_vifs_from_node(task)
        with task_manager.acquire(self.context, self.node.uuid) as task:
            result = network.get_node_vif_ids(task)
        self.assertEqual({}, result['ports'])
        self.assertEqual({}, result['portgroups'])


class TestRemoveVifsTestCase(db_base.DbTestCase):

    def setUp(self):
        super(TestRemoveVifsTestCase, self).setUp()
        self.node = object_utils.create_test_node(
            self.context,
            network_interface='flat',
            provision_state=states.DELETING)

    @mock.patch.object(neutron_common, 'unbind_neutron_port', autospec=True)
    def test_remove_vifs_from_node_failure(self, mock_unbind):
        db_utils.create_test_port(
            node_id=self.node.id, address='aa:bb:cc:dd:ee:ff',
            internal_info={driver_common.TENANT_VIF_KEY: 'test-vif-A'})
        db_utils.create_test_portgroup(
            node_id=self.node.id, address='dd:ee:ff:aa:bb:cc',
            internal_info={driver_common.TENANT_VIF_KEY: 'test-vif-B'})
        mock_unbind.side_effect = [exception.NetworkError, None]
        with task_manager.acquire(self.context, self.node.uuid) as task:
            network.remove_vifs_from_node(task)
        with task_manager.acquire(self.context, self.node.uuid) as task:
            result = network.get_node_vif_ids(task)
        self.assertEqual({}, result['ports'])
        self.assertEqual({}, result['portgroups'])
        self.assertEqual(2, mock_unbind.call_count)


class GetPortgroupByIdTestCase(db_base.DbTestCase):
    def test_portgroup_by_id(self):
        node = object_utils.create_test_node(self.context)
        portgroup = object_utils.create_test_portgroup(self.context,
                                                       node_id=node.id)
        object_utils.create_test_portgroup(self.context,
                                           node_id=node.id,
                                           uuid=uuidutils.generate_uuid(),
                                           address='00:11:22:33:44:55',
                                           name='pg2')
        with task_manager.acquire(self.context, node.uuid) as task:
            res = network.get_portgroup_by_id(task, portgroup.id)
        self.assertEqual(portgroup.id, res.id)

    def test_portgroup_by_id_no_such_portgroup(self):
        node = object_utils.create_test_node(self.context)
        object_utils.create_test_portgroup(self.context, node_id=node.id)
        with task_manager.acquire(self.context, node.uuid) as task:
            portgroup_id = 'invalid-portgroup-id'
            res = network.get_portgroup_by_id(task, portgroup_id)
        self.assertIsNone(res)


class GetPortsByPortgroupIdTestCase(db_base.DbTestCase):

    def test_ports_by_portgroup_id(self):
        node = object_utils.create_test_node(self.context)
        portgroup = object_utils.create_test_portgroup(self.context,
                                                       node_id=node.id)
        port = object_utils.create_test_port(self.context, node_id=node.id,
                                             portgroup_id=portgroup.id)
        object_utils.create_test_port(self.context, node_id=node.id,
                                      uuid=uuidutils.generate_uuid(),
                                      address='00:11:22:33:44:55')
        with task_manager.acquire(self.context, node.uuid) as task:
            res = network.get_ports_by_portgroup_id(task, portgroup.id)
        self.assertEqual([port.id], [p.id for p in res])

    def test_ports_by_portgroup_id_empty(self):
        node = object_utils.create_test_node(self.context)
        portgroup = object_utils.create_test_portgroup(self.context,
                                                       node_id=node.id)
        with task_manager.acquire(self.context, node.uuid) as task:
            res = network.get_ports_by_portgroup_id(task, portgroup.id)
        self.assertEqual([], res)


class GetPhysnetsForNodeTestCase(db_base.DbTestCase):

    def test_get_physnets_for_node_no_ports(self):
        node = object_utils.create_test_node(self.context)
        with task_manager.acquire(self.context, node.uuid) as task:
            res = network.get_physnets_for_node(task)
        self.assertEqual(set(), res)

    def test_get_physnets_for_node_excludes_None(self):
        node = object_utils.create_test_node(self.context)
        object_utils.create_test_port(self.context, node_id=node.id)
        with task_manager.acquire(self.context, node.uuid) as task:
            res = network.get_physnets_for_node(task)
        self.assertEqual(set(), res)

    def test_get_physnets_for_node_multiple_ports(self):
        node = object_utils.create_test_node(self.context)
        object_utils.create_test_port(self.context, node_id=node.id,
                                      physical_network='physnet1')
        object_utils.create_test_port(self.context, node_id=node.id,
                                      uuid=uuidutils.generate_uuid(),
                                      address='00:11:22:33:44:55',
                                      physical_network='physnet2')
        with task_manager.acquire(self.context, node.uuid) as task:
            res = network.get_physnets_for_node(task)
        self.assertEqual({'physnet1', 'physnet2'}, res)


class GetPhysnetsByPortgroupID(db_base.DbTestCase):

    def setUp(self):
        super(GetPhysnetsByPortgroupID, self).setUp()
        self.node = object_utils.create_test_node(self.context)
        self.portgroup = object_utils.create_test_portgroup(
            self.context, node_id=self.node.id)

    def _test(self, expected_result, exclude_port=None):
        with task_manager.acquire(self.context, self.node.uuid) as task:
            result = network.get_physnets_by_portgroup_id(task,
                                                          self.portgroup.id,
                                                          exclude_port)
        self.assertEqual(expected_result, result)

    def test_empty(self):
        self._test(set())

    def test_one_port(self):
        object_utils.create_test_port(self.context, node_id=self.node.id,
                                      portgroup_id=self.portgroup.id,
                                      physical_network='physnet1')
        self._test({'physnet1'})

    def test_two_ports(self):
        object_utils.create_test_port(self.context, node_id=self.node.id,
                                      portgroup_id=self.portgroup.id,
                                      physical_network='physnet1')
        object_utils.create_test_port(self.context, node_id=self.node.id,
                                      uuid=uuidutils.generate_uuid(),
                                      address='00:11:22:33:44:55',
                                      portgroup_id=self.portgroup.id,
                                      physical_network='physnet1')
        self._test({'physnet1'})

    def test_exclude_port(self):
        object_utils.create_test_port(self.context, node_id=self.node.id,
                                      portgroup_id=self.portgroup.id,
                                      physical_network='physnet1')
        port2 = object_utils.create_test_port(self.context,
                                              node_id=self.node.id,
                                              uuid=uuidutils.generate_uuid(),
                                              address='00:11:22:33:44:55',
                                              portgroup_id=self.portgroup.id,
                                              physical_network='physnet2')
        self._test({'physnet1'}, port2)

    def test_exclude_port_no_id(self):
        # During port creation there may be no 'id' field.
        object_utils.create_test_port(self.context, node_id=self.node.id,
                                      portgroup_id=self.portgroup.id,
                                      physical_network='physnet1')
        port2 = object_utils.get_test_port(self.context,
                                           node_id=self.node.id,
                                           uuid=uuidutils.generate_uuid(),
                                           address='00:11:22:33:44:55',
                                           portgroup_id=self.portgroup.id,
                                           physical_network='physnet2')
        self._test({'physnet1'}, port2)

    def test_two_ports_inconsistent(self):
        object_utils.create_test_port(self.context, node_id=self.node.id,
                                      portgroup_id=self.portgroup.id,
                                      physical_network='physnet1')
        object_utils.create_test_port(self.context, node_id=self.node.id,
                                      uuid=uuidutils.generate_uuid(),
                                      address='00:11:22:33:44:55',
                                      portgroup_id=self.portgroup.id,
                                      physical_network='physnet2')
        with task_manager.acquire(self.context, self.node.uuid) as task:
            self.assertRaises(exception.PortgroupPhysnetInconsistent,
                              network.get_physnets_by_portgroup_id,
                              task, self.portgroup.id)
