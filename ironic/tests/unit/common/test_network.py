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

from oslo_utils import uuidutils

from ironic.common import network
from ironic.conductor import task_manager
from ironic.tests.unit.conductor import mgr_utils
from ironic.tests.unit.db import base as db_base
from ironic.tests.unit.db import utils as db_utils
from ironic.tests.unit.objects import utils as object_utils


class TestNetwork(db_base.DbTestCase):

    def setUp(self):
        super(TestNetwork, self).setUp()
        mgr_utils.mock_the_extension_manager(driver='fake')
        self.node = object_utils.create_test_node(self.context)

    def test_get_node_vif_ids_no_ports_no_portgroups(self):
        expected = {'portgroups': {},
                    'ports': {}}
        with task_manager.acquire(self.context, self.node.uuid) as task:
            result = network.get_node_vif_ids(task)
        self.assertEqual(expected, result)

    def test_get_node_vif_ids_one_port(self):
        port1 = db_utils.create_test_port(node_id=self.node.id,
                                          address='aa:bb:cc:dd:ee:ff',
                                          uuid=uuidutils.generate_uuid(),
                                          extra={'vif_port_id': 'test-vif-A'},
                                          driver='fake')
        expected = {'portgroups': {},
                    'ports': {port1.uuid: 'test-vif-A'}}
        with task_manager.acquire(self.context, self.node.uuid) as task:
            result = network.get_node_vif_ids(task)
        self.assertEqual(expected, result)

    def test_get_node_vif_ids_one_portgroup(self):
        pg1 = db_utils.create_test_portgroup(
            node_id=self.node.id,
            extra={'vif_port_id': 'test-vif-A'})

        expected = {'portgroups': {pg1.uuid: 'test-vif-A'},
                    'ports': {}}
        with task_manager.acquire(self.context, self.node.uuid) as task:
            result = network.get_node_vif_ids(task)
        self.assertEqual(expected, result)

    def test_get_node_vif_ids_two_ports(self):
        port1 = db_utils.create_test_port(node_id=self.node.id,
                                          address='aa:bb:cc:dd:ee:ff',
                                          uuid=uuidutils.generate_uuid(),
                                          extra={'vif_port_id': 'test-vif-A'},
                                          driver='fake')
        port2 = db_utils.create_test_port(node_id=self.node.id,
                                          address='dd:ee:ff:aa:bb:cc',
                                          uuid=uuidutils.generate_uuid(),
                                          extra={'vif_port_id': 'test-vif-B'},
                                          driver='fake')
        expected = {'portgroups': {},
                    'ports': {port1.uuid: 'test-vif-A',
                              port2.uuid: 'test-vif-B'}}
        with task_manager.acquire(self.context, self.node.uuid) as task:
            result = network.get_node_vif_ids(task)
        self.assertEqual(expected, result)

    def test_get_node_vif_ids_two_portgroups(self):
        pg1 = db_utils.create_test_portgroup(
            node_id=self.node.id,
            extra={'vif_port_id': 'test-vif-A'})
        pg2 = db_utils.create_test_portgroup(
            uuid=uuidutils.generate_uuid(),
            address='dd:ee:ff:aa:bb:cc',
            node_id=self.node.id,
            name='barname',
            extra={'vif_port_id': 'test-vif-B'})
        expected = {'portgroups': {pg1.uuid: 'test-vif-A',
                                   pg2.uuid: 'test-vif-B'},
                    'ports': {}}
        with task_manager.acquire(self.context, self.node.uuid) as task:
            result = network.get_node_vif_ids(task)
        self.assertEqual(expected, result)

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
