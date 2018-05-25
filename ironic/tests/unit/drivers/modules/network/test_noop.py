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

from ironic.conductor import task_manager
from ironic.drivers.modules.network import noop
from ironic.tests.unit.db import base as db_base
from ironic.tests.unit.objects import utils


class NoopInterfaceTestCase(db_base.DbTestCase):

    def setUp(self):
        super(NoopInterfaceTestCase, self).setUp()
        self.interface = noop.NoopNetwork()
        self.node = utils.create_test_node(self.context,
                                           network_interface='noop')
        self.port = utils.create_test_port(
            self.context, node_id=self.node.id, address='52:54:00:cf:2d:32')

    def test_get_properties(self):
        result = self.interface.get_properties()
        self.assertEqual({}, result)

    def test_validate(self):
        with task_manager.acquire(self.context, self.node.id) as task:
            self.interface.validate(task)

    def test_port_changed(self):
        with task_manager.acquire(self.context, self.node.id) as task:
            self.interface.port_changed(task, self.port)

    def test_portgroup_changed(self):
        portgroup = utils.create_test_portgroup(self.context)
        with task_manager.acquire(self.context, self.node.id) as task:
            self.interface.portgroup_changed(task, portgroup)

    def test_vif_attach(self):
        vif = {'id': 'vif-id'}
        with task_manager.acquire(self.context, self.node.id) as task:
            self.interface.vif_attach(task, vif)

    def test_vif_detach(self):
        vif_id = 'vif-id'
        with task_manager.acquire(self.context, self.node.id) as task:
            self.interface.vif_detach(task, vif_id)

    def test_vif_list(self):
        with task_manager.acquire(self.context, self.node.id) as task:
            result = self.interface.vif_list(task)
        self.assertEqual([], result)

    def test_get_current_vif(self):
        with task_manager.acquire(self.context, self.node.id) as task:
            result = self.interface.get_current_vif(task, self.port)
        self.assertIsNone(result)

    def test_add_provisioning_network(self):
        with task_manager.acquire(self.context, self.node.id) as task:
            self.interface.add_provisioning_network(task)

    def test_remove_provisioning_network(self):
        with task_manager.acquire(self.context, self.node.id) as task:
            self.interface.remove_provisioning_network(task)

    def test_configure_tenant_networks(self):
        with task_manager.acquire(self.context, self.node.id) as task:
            self.interface.configure_tenant_networks(task)

    def test_unconfigure_tenant_networks(self):
        with task_manager.acquire(self.context, self.node.id) as task:
            self.interface.unconfigure_tenant_networks(task)

    def test_add_cleaning_network(self):
        with task_manager.acquire(self.context, self.node.id) as task:
            self.interface.add_cleaning_network(task)

    def test_remove_cleaning_network(self):
        with task_manager.acquire(self.context, self.node.id) as task:
            self.interface.remove_cleaning_network(task)
