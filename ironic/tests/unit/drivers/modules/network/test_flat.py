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
from neutronclient.common import exceptions as neutron_exceptions
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
VIFMIXINPATH = 'ironic.drivers.modules.network.common.NeutronVIFPortIDMixin'


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

    @mock.patch('%s.vif_list' % VIFMIXINPATH)
    def test_vif_list(self, mock_vif_list):
        with task_manager.acquire(self.context, self.node.id) as task:
            self.interface.vif_list(task)
            mock_vif_list.assert_called_once_with(task)

    @mock.patch('%s.vif_attach' % VIFMIXINPATH)
    def test_vif_attach(self, mock_vif_attach):
        vif = mock.MagicMock()
        with task_manager.acquire(self.context, self.node.id) as task:
            self.interface.vif_attach(task, vif)
            mock_vif_attach.assert_called_once_with(task, vif)

    @mock.patch('%s.vif_detach' % VIFMIXINPATH)
    def test_vif_detach(self, mock_vif_detach):
        vif_id = "vif"
        with task_manager.acquire(self.context, self.node.id) as task:
            self.interface.vif_detach(task, vif_id)
            mock_vif_detach.assert_called_once_with(task, vif_id)

    @mock.patch('%s.port_changed' % VIFMIXINPATH)
    def test_vif_port_changed(self, mock_p_changed):
        port = mock.MagicMock()
        with task_manager.acquire(self.context, self.node.id) as task:
            self.interface.port_changed(task, port)
            mock_p_changed.assert_called_once_with(task, port)

    @mock.patch.object(flat_interface, 'LOG')
    def test_init_no_cleaning_network(self, mock_log):
        self.config(cleaning_network=None, group='neutron')
        flat_interface.FlatNetwork()
        self.assertTrue(mock_log.warning.called)

    @mock.patch.object(neutron, 'validate_network', autospec=True)
    def test_validate(self, validate_mock):
        with task_manager.acquire(self.context, self.node.id) as task:
            self.interface.validate(task)
        validate_mock.assert_called_once_with(CONF.neutron.cleaning_network,
                                              'cleaning network')

    @mock.patch.object(neutron, 'validate_network',
                       side_effect=lambda n, t: n)
    @mock.patch.object(neutron, 'add_ports_to_network')
    @mock.patch.object(neutron, 'rollback_ports')
    def test_add_cleaning_network(self, rollback_mock, add_mock,
                                  validate_mock):
        add_mock.return_value = {self.port.uuid: 'vif-port-id'}
        with task_manager.acquire(self.context, self.node.id) as task:
            self.interface.add_cleaning_network(task)
            rollback_mock.assert_called_once_with(
                task, CONF.neutron.cleaning_network)
            add_mock.assert_called_once_with(
                task, CONF.neutron.cleaning_network)
            validate_mock.assert_called_once_with(
                CONF.neutron.cleaning_network,
                'cleaning network')
        self.port.refresh()
        self.assertEqual('vif-port-id',
                         self.port.internal_info['cleaning_vif_port_id'])

    @mock.patch.object(neutron, 'validate_network',
                       side_effect=lambda n, t: n)
    @mock.patch.object(neutron, 'remove_ports_from_network')
    def test_remove_cleaning_network(self, remove_mock, validate_mock):
        with task_manager.acquire(self.context, self.node.id) as task:
            self.interface.remove_cleaning_network(task)
            remove_mock.assert_called_once_with(
                task, CONF.neutron.cleaning_network)
            validate_mock.assert_called_once_with(
                CONF.neutron.cleaning_network,
                'cleaning network')
        self.port.refresh()
        self.assertNotIn('cleaning_vif_port_id', self.port.internal_info)

    @mock.patch.object(neutron, 'get_client')
    def test_add_provisioning_network_set_binding_host_id(
            self, client_mock):
        upd_mock = mock.Mock()
        client_mock.return_value.update_port = upd_mock
        instance_info = self.node.instance_info
        instance_info['nova_host_id'] = 'nova_host_id'
        self.node.instance_info = instance_info
        self.node.save()
        extra = {'vif_port_id': 'foo'}
        utils.create_test_port(self.context, node_id=self.node.id,
                               address='52:54:00:cf:2d:33', extra=extra,
                               uuid=uuidutils.generate_uuid())
        exp_body = {'port': {'binding:host_id': 'nova_host_id'}}
        with task_manager.acquire(self.context, self.node.id) as task:
            self.interface.add_provisioning_network(task)
        upd_mock.assert_called_once_with('foo', exp_body)

    @mock.patch.object(neutron, 'get_client')
    def test_add_provisioning_network_set_binding_host_id_portgroup(
            self, client_mock):
        upd_mock = mock.Mock()
        client_mock.return_value.update_port = upd_mock
        instance_info = self.node.instance_info
        instance_info['nova_host_id'] = 'nova_host_id'
        self.node.instance_info = instance_info
        self.node.save()
        internal_info = {'tenant_vif_port_id': 'foo'}
        utils.create_test_portgroup(
            self.context, node_id=self.node.id, internal_info=internal_info,
            uuid=uuidutils.generate_uuid())
        utils.create_test_port(
            self.context, node_id=self.node.id, address='52:54:00:cf:2d:33',
            extra={'vif_port_id': 'bar'}, uuid=uuidutils.generate_uuid())
        exp_body = {'port': {'binding:host_id': 'nova_host_id'}}
        with task_manager.acquire(self.context, self.node.id) as task:
            self.interface.add_provisioning_network(task)
        upd_mock.assert_has_calls([
            mock.call('bar', exp_body), mock.call('foo', exp_body)
        ])

    @mock.patch.object(neutron, 'get_client')
    def test_add_provisioning_network_no_binding_host_id(
            self, client_mock):
        upd_mock = mock.Mock()
        client_mock.return_value.update_port = upd_mock
        instance_info = self.node.instance_info
        instance_info.pop('nova_host_id', None)
        self.node.instance_info = instance_info
        self.node.save()
        extra = {'vif_port_id': 'foo'}
        utils.create_test_port(self.context, node_id=self.node.id,
                               address='52:54:00:cf:2d:33', extra=extra,
                               uuid=uuidutils.generate_uuid())
        with task_manager.acquire(self.context, self.node.id) as task:
            self.interface.add_provisioning_network(task)
            self.assertFalse(upd_mock.called)

    @mock.patch.object(neutron, 'get_client')
    def test_add_provisioning_network_binding_host_id_raise(
            self, client_mock):
        client_mock.return_value.update_port.side_effect = \
            (neutron_exceptions.ConnectionFailed())
        instance_info = self.node.instance_info
        instance_info['nova_host_id'] = 'nova_host_id'
        self.node.instance_info = instance_info
        self.node.save()
        extra = {'vif_port_id': 'foo'}
        utils.create_test_port(self.context, node_id=self.node.id,
                               address='52:54:00:cf:2d:33', extra=extra,
                               uuid=uuidutils.generate_uuid())
        with task_manager.acquire(self.context, self.node.id) as task:
            self.assertRaises(exception.NetworkError,
                              self.interface.add_provisioning_network,
                              task)
