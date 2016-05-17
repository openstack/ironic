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

import mock
from oslo_config import cfg
from oslo_utils import uuidutils

from ironic.common import exception
from ironic.common import neutron
from ironic.conductor import task_manager
from ironic.drivers.modules.network import flat as flat_interface
from ironic.tests.unit.conductor import mgr_utils
from ironic.tests.unit.db import base as db_base
from ironic.tests.unit.objects import utils

CONF = cfg.CONF


class TestFlatInterface(db_base.DbTestCase):

    def setUp(self):
        super(TestFlatInterface, self).setUp()
        self.config(enabled_drivers=['fake'])
        mgr_utils.mock_the_extension_manager()
        self.interface = flat_interface.FlatNetwork()
        self.node = utils.create_test_node(self.context)
        self.port = utils.create_test_port(
            self.context, node_id=self.node.id,
            internal_info={
                'cleaning_vif_port_id': uuidutils.generate_uuid()})

    @mock.patch.object(flat_interface, 'LOG')
    def test_init_incorrect_cleaning_net(self, mock_log):
        self.config(cleaning_network_uuid=None, group='neutron')
        flat_interface.FlatNetwork()
        self.assertTrue(mock_log.warning.called)

    @mock.patch.object(neutron, 'add_ports_to_network')
    @mock.patch.object(neutron, 'rollback_ports')
    def test_add_cleaning_network(self, rollback_mock, add_mock):
        add_mock.return_value = {self.port.uuid: 'vif-port-id'}
        with task_manager.acquire(self.context, self.node.id) as task:
            self.interface.add_cleaning_network(task)
            rollback_mock.assert_called_once_with(
                task, CONF.neutron.cleaning_network_uuid)
            add_mock.assert_called_once_with(
                task, CONF.neutron.cleaning_network_uuid, is_flat=True)
        self.port.refresh()
        self.assertEqual('vif-port-id',
                         self.port.internal_info['cleaning_vif_port_id'])

    @mock.patch.object(neutron, 'add_ports_to_network')
    @mock.patch.object(neutron, 'rollback_ports')
    def test_add_cleaning_network_no_cleaning_net_uuid(self, rollback_mock,
                                                       add_mock):
        self.config(cleaning_network_uuid='abc', group='neutron')
        with task_manager.acquire(self.context, self.node.id) as task:
            self.assertRaises(exception.InvalidParameterValue,
                              self.interface.add_cleaning_network, task)
            self.assertFalse(rollback_mock.called)
            self.assertFalse(add_mock.called)

    @mock.patch.object(neutron, 'remove_ports_from_network')
    def test_remove_cleaning_network(self, remove_mock):
        with task_manager.acquire(self.context, self.node.id) as task:
            self.interface.remove_cleaning_network(task)
            remove_mock.assert_called_once_with(
                task, CONF.neutron.cleaning_network_uuid)
        self.port.refresh()
        self.assertNotIn('cleaning_vif_port_id', self.port.internal_info)

    def test_unconfigure_tenant_networks(self):
        with task_manager.acquire(self.context, self.node.id) as task:
            self.interface.unconfigure_tenant_networks(task)
            self.port.refresh()
            self.assertNotIn('vif_port_id', self.port.extra)
