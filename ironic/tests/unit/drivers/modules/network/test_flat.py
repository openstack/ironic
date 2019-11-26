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
from ironic.tests.unit.db import base as db_base
from ironic.tests.unit.objects import utils

CONF = cfg.CONF
VIFMIXINPATH = 'ironic.drivers.modules.network.common.NeutronVIFPortIDMixin'


class TestFlatInterface(db_base.DbTestCase):

    def setUp(self):
        super(TestFlatInterface, self).setUp()
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
            validate_mock.assert_called_once_with(
                CONF.neutron.cleaning_network,
                'cleaning network', context=task.context)

    @mock.patch.object(neutron, 'validate_network', autospec=True)
    def test_validate_from_node(self, validate_mock):
        cleaning_network_uuid = '3aea0de6-4b92-44da-9aa0-52d134c83fdf'
        driver_info = self.node.driver_info
        driver_info['cleaning_network'] = cleaning_network_uuid
        self.node.driver_info = driver_info
        self.node.save()
        with task_manager.acquire(self.context, self.node.id) as task:
            self.interface.validate(task)
        validate_mock.assert_called_once_with(
            cleaning_network_uuid,
            'cleaning network', context=task.context)

    @mock.patch.object(neutron, 'validate_network',
                       side_effect=lambda n, t, context=None: n)
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
                CONF.neutron.cleaning_network, 'cleaning network',
                context=task.context)
        self.port.refresh()
        self.assertEqual('vif-port-id',
                         self.port.internal_info['cleaning_vif_port_id'])

    @mock.patch.object(neutron, 'validate_network',
                       side_effect=lambda n, t, context=None: n)
    @mock.patch.object(neutron, 'add_ports_to_network')
    @mock.patch.object(neutron, 'rollback_ports')
    def test_add_cleaning_network_from_node(self, rollback_mock, add_mock,
                                            validate_mock):
        add_mock.return_value = {self.port.uuid: 'vif-port-id'}
        # Make sure that changing the network UUID works
        for cleaning_network_uuid in ['3aea0de6-4b92-44da-9aa0-52d134c83fdf',
                                      '438be438-6aae-4fb1-bbcb-613ad7a38286']:
            driver_info = self.node.driver_info
            driver_info['cleaning_network'] = cleaning_network_uuid
            self.node.driver_info = driver_info
            self.node.save()
            with task_manager.acquire(self.context, self.node.id) as task:
                self.interface.add_cleaning_network(task)
                rollback_mock.assert_called_with(
                    task, cleaning_network_uuid)
                add_mock.assert_called_with(task, cleaning_network_uuid)
                validate_mock.assert_called_with(
                    cleaning_network_uuid,
                    'cleaning network', context=task.context)
        self.port.refresh()
        self.assertEqual('vif-port-id',
                         self.port.internal_info['cleaning_vif_port_id'])

    @mock.patch.object(neutron, 'validate_network',
                       side_effect=lambda n, t, context=None: n)
    @mock.patch.object(neutron, 'remove_ports_from_network')
    def test_remove_cleaning_network(self, remove_mock, validate_mock):
        with task_manager.acquire(self.context, self.node.id) as task:
            self.interface.remove_cleaning_network(task)
            remove_mock.assert_called_once_with(
                task, CONF.neutron.cleaning_network)
            validate_mock.assert_called_once_with(
                CONF.neutron.cleaning_network,
                'cleaning network', context=task.context)
        self.port.refresh()
        self.assertNotIn('cleaning_vif_port_id', self.port.internal_info)

    @mock.patch.object(neutron, 'validate_network',
                       side_effect=lambda n, t, context=None: n)
    @mock.patch.object(neutron, 'remove_ports_from_network')
    def test_remove_cleaning_network_from_node(self, remove_mock,
                                               validate_mock):
        cleaning_network_uuid = '3aea0de6-4b92-44da-9aa0-52d134c83fdf'
        driver_info = self.node.driver_info
        driver_info['cleaning_network'] = cleaning_network_uuid
        self.node.driver_info = driver_info
        self.node.save()
        with task_manager.acquire(self.context, self.node.id) as task:
            self.interface.remove_cleaning_network(task)
            remove_mock.assert_called_once_with(task, cleaning_network_uuid)
            validate_mock.assert_called_once_with(
                cleaning_network_uuid,
                'cleaning network', context=task.context)
        self.port.refresh()
        self.assertNotIn('cleaning_vif_port_id', self.port.internal_info)

    @mock.patch.object(neutron, 'get_client')
    def test__bind_flat_ports_set_binding_host_id(self, client_mock):
        upd_mock = mock.Mock()
        client_mock.return_value.update_port = upd_mock
        extra = {'vif_port_id': 'foo'}
        utils.create_test_port(self.context, node_id=self.node.id,
                               address='52:54:00:cf:2d:33', extra=extra,
                               uuid=uuidutils.generate_uuid())
        exp_body = {'port': {'binding:host_id': self.node.uuid,
                             'binding:vnic_type': neutron.VNIC_BAREMETAL,
                             'mac_address': '52:54:00:cf:2d:33'}}
        with task_manager.acquire(self.context, self.node.id) as task:
            self.interface._bind_flat_ports(task)
        upd_mock.assert_called_once_with('foo', exp_body)

    @mock.patch.object(neutron, 'get_client')
    def test__bind_flat_ports_set_binding_host_id_portgroup(self, client_mock):
        upd_mock = mock.Mock()
        client_mock.return_value.update_port = upd_mock
        internal_info = {'tenant_vif_port_id': 'foo'}
        utils.create_test_portgroup(
            self.context, node_id=self.node.id, internal_info=internal_info,
            uuid=uuidutils.generate_uuid())
        utils.create_test_port(
            self.context, node_id=self.node.id, address='52:54:00:cf:2d:33',
            extra={'vif_port_id': 'bar'}, uuid=uuidutils.generate_uuid())
        exp_body1 = {'port': {'binding:host_id': self.node.uuid,
                              'binding:vnic_type': neutron.VNIC_BAREMETAL,
                              'mac_address': '52:54:00:cf:2d:33'}}
        exp_body2 = {'port': {'binding:host_id': self.node.uuid,
                              'binding:vnic_type': neutron.VNIC_BAREMETAL,
                              'mac_address': '52:54:00:cf:2d:31'}}
        with task_manager.acquire(self.context, self.node.id) as task:
            self.interface._bind_flat_ports(task)
        upd_mock.assert_has_calls([
            mock.call('bar', exp_body1), mock.call('foo', exp_body2)])

    @mock.patch.object(neutron, 'unbind_neutron_port')
    def test__unbind_flat_ports(self, unbind_neutron_port_mock):
        extra = {'vif_port_id': 'foo'}
        utils.create_test_port(self.context, node_id=self.node.id,
                               address='52:54:00:cf:2d:33', extra=extra,
                               uuid=uuidutils.generate_uuid())
        with task_manager.acquire(self.context, self.node.id) as task:
            self.interface._unbind_flat_ports(task)
        unbind_neutron_port_mock.assert_called_once_with('foo',
                                                         context=self.context)

    @mock.patch.object(neutron, 'unbind_neutron_port')
    def test__unbind_flat_ports_portgroup(self, unbind_neutron_port_mock):
        internal_info = {'tenant_vif_port_id': 'foo'}
        utils.create_test_portgroup(self.context, node_id=self.node.id,
                                    internal_info=internal_info,
                                    uuid=uuidutils.generate_uuid())
        extra = {'vif_port_id': 'bar'}
        utils.create_test_port(self.context, node_id=self.node.id,
                               address='52:54:00:cf:2d:33', extra=extra,
                               uuid=uuidutils.generate_uuid())
        with task_manager.acquire(self.context, self.node.id) as task:
            self.interface._unbind_flat_ports(task)
        unbind_neutron_port_mock.has_calls(
            [mock.call('foo', context=self.context),
             mock.call('bar', context=self.context)])

    @mock.patch.object(neutron, 'get_client')
    def test__bind_flat_ports_set_binding_host_id_raise(self, client_mock):
        client_mock.return_value.update_port.side_effect = \
            (neutron_exceptions.ConnectionFailed())
        extra = {'vif_port_id': 'foo'}
        utils.create_test_port(self.context, node_id=self.node.id,
                               address='52:54:00:cf:2d:33', extra=extra,
                               uuid=uuidutils.generate_uuid())
        with task_manager.acquire(self.context, self.node.id) as task:
            self.assertRaises(exception.NetworkError,
                              self.interface._bind_flat_ports, task)

    @mock.patch.object(flat_interface.FlatNetwork, '_bind_flat_ports')
    def test_add_rescuing_network(self, bind_mock):
        with task_manager.acquire(self.context, self.node.id) as task:
            self.interface.add_rescuing_network(task)
            bind_mock.assert_called_once_with(task)

    @mock.patch.object(flat_interface.FlatNetwork, '_unbind_flat_ports')
    def test_remove_rescuing_network(self, unbind_mock):
        with task_manager.acquire(self.context, self.node.id) as task:
            self.interface.remove_rescuing_network(task)
            unbind_mock.assert_called_once_with(task)

    @mock.patch.object(flat_interface.FlatNetwork, '_bind_flat_ports')
    def test_add_provisioning_network(self, bind_mock):
        with task_manager.acquire(self.context, self.node.id) as task:
            self.interface.add_provisioning_network(task)
            bind_mock.assert_called_once_with(task)

    @mock.patch.object(flat_interface.FlatNetwork, '_unbind_flat_ports')
    def test_remove_provisioning_network(self, unbind_mock):
        with task_manager.acquire(self.context, self.node.id) as task:
            self.interface.remove_provisioning_network(task)
            unbind_mock.assert_called_once_with(task)

    @mock.patch.object(neutron, 'validate_network',
                       side_effect=lambda n, t, context=None: n)
    @mock.patch.object(neutron, 'add_ports_to_network')
    @mock.patch.object(neutron, 'rollback_ports')
    def test_add_inspection_network(self, rollback_mock, add_mock,
                                    validate_mock):
        add_mock.return_value = {self.port.uuid: 'vif-port-id'}
        with task_manager.acquire(self.context, self.node.id) as task:
            self.interface.add_inspection_network(task)
            rollback_mock.assert_called_once_with(
                task, CONF.neutron.inspection_network)
            add_mock.assert_called_once_with(
                task, CONF.neutron.inspection_network)
            validate_mock.assert_called_once_with(
                CONF.neutron.inspection_network, 'inspection network',
                context=task.context)
        self.port.refresh()
        self.assertEqual('vif-port-id',
                         self.port.internal_info['inspection_vif_port_id'])

    @mock.patch.object(neutron, 'validate_network',
                       side_effect=lambda n, t, context=None: n)
    @mock.patch.object(neutron, 'add_ports_to_network')
    @mock.patch.object(neutron, 'rollback_ports')
    def test_add_inspection_network_from_node(self, rollback_mock, add_mock,
                                              validate_mock):
        add_mock.return_value = {self.port.uuid: 'vif-port-id'}
        # Make sure that changing the network UUID works
        for inspection_network_uuid in [
                '3aea0de6-4b92-44da-9aa0-52d134c83fdf',
                '438be438-6aae-4fb1-bbcb-613ad7a38286']:
            driver_info = self.node.driver_info
            driver_info['inspection_network'] = inspection_network_uuid
            self.node.driver_info = driver_info
            self.node.save()
            with task_manager.acquire(self.context, self.node.id) as task:
                self.interface.add_inspection_network(task)
                rollback_mock.assert_called_with(
                    task, inspection_network_uuid)
                add_mock.assert_called_with(task, inspection_network_uuid)
                validate_mock.assert_called_with(
                    inspection_network_uuid,
                    'inspection network', context=task.context)
        self.port.refresh()
        self.assertEqual('vif-port-id',
                         self.port.internal_info['inspection_vif_port_id'])

    @mock.patch.object(neutron, 'validate_network',
                       side_effect=lambda n, t, context=None: n)
    def test_validate_inspection(self, validate_mock):
        inspection_network_uuid = '3aea0de6-4b92-44da-9aa0-52d134c83fdf'
        driver_info = self.node.driver_info
        driver_info['inspection_network'] = inspection_network_uuid
        self.node.driver_info = driver_info
        self.node.save()
        with task_manager.acquire(self.context, self.node.id) as task:
            self.interface.validate_inspection(task)
            validate_mock.assert_called_once_with(
                inspection_network_uuid, 'inspection network',
                context=task.context),

    def test_validate_inspection_exc(self):
        self.config(inspection_network="", group='neutron')
        with task_manager.acquire(self.context, self.node.id) as task:
            self.assertRaises(exception.UnsupportedDriverExtension,
                              self.interface.validate_inspection, task)
