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

from ironic.common import network
from ironic.common import utils
from ironic.conductor import task_manager
from ironic.db import api as dbapi
from ironic.openstack.common import context
from ironic.tests import base
from ironic.tests.conductor import utils as mgr_utils
from ironic.tests.db import utils as db_utils
from ironic.tests.objects import utils as object_utils


class TestNetwork(base.TestCase):

    def setUp(self):
        super(TestNetwork, self).setUp()
        mgr_utils.mock_the_extension_manager(driver='fake')
        self.dbapi = dbapi.get_instance()
        self.context = context.get_admin_context()
        self.node = object_utils.create_test_node(self.context)

    def _create_test_port(self, **kwargs):
        p = db_utils.get_test_port(**kwargs)
        return self.dbapi.create_port(p)

    def test_get_node_vif_ids_no_ports(self):
        expected = {}
        with task_manager.acquire(self.context, self.node.uuid) as task:
            result = network.get_node_vif_ids(task)
        self.assertEqual(expected, result)

    def test_get_node_vif_ids_one_port(self):
        port1 = self._create_test_port(node_id=self.node.id,
                                       id=6,
                                       address='aa:bb:cc',
                                       uuid=utils.generate_uuid(),
                                       extra={'vif_port_id': 'test-vif-A'},
                                       driver='fake')
        expected = {port1.uuid: 'test-vif-A'}
        with task_manager.acquire(self.context, self.node.uuid) as task:
            result = network.get_node_vif_ids(task)
        self.assertEqual(expected, result)

    def test_get_node_vif_ids_two_ports(self):
        port1 = self._create_test_port(node_id=self.node.id,
                                       id=6,
                                       address='aa:bb:cc',
                                       uuid=utils.generate_uuid(),
                                       extra={'vif_port_id': 'test-vif-A'},
                                       driver='fake')
        port2 = self._create_test_port(node_id=self.node.id,
                                       id=7,
                                       address='dd:ee:ff',
                                       uuid=utils.generate_uuid(),
                                       extra={'vif_port_id': 'test-vif-B'},
                                       driver='fake')
        expected = {port1.uuid: 'test-vif-A', port2.uuid: 'test-vif-B'}
        with task_manager.acquire(self.context, self.node.uuid) as task:
            result = network.get_node_vif_ids(task)
        self.assertEqual(expected, result)
