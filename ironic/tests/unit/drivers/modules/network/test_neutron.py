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

import copy

import mock
from neutronclient.common import exceptions as neutron_exceptions
from oslo_config import cfg
from oslo_utils import uuidutils

from ironic.common import exception
from ironic.common import neutron as neutron_common
from ironic.conductor import task_manager
from ironic.drivers.modules.network import neutron
from ironic.tests.unit.conductor import mgr_utils
from ironic.tests.unit.db import base as db_base
from ironic.tests.unit.objects import utils

CONF = cfg.CONF
CLIENT_ID1 = '20:00:55:04:01:fe:80:00:00:00:00:00:00:00:02:c9:02:00:23:13:92'
CLIENT_ID2 = '20:00:55:04:01:fe:80:00:00:00:00:00:00:00:02:c9:02:00:23:13:93'


class NeutronInterfaceTestCase(db_base.DbTestCase):

    def setUp(self):
        super(NeutronInterfaceTestCase, self).setUp()
        self.config(enabled_drivers=['fake'])
        mgr_utils.mock_the_extension_manager()
        self.interface = neutron.NeutronNetwork()
        self.node = utils.create_test_node(self.context,
                                           network_interface='neutron')
        self.port = utils.create_test_port(
            self.context, node_id=self.node.id,
            address='52:54:00:cf:2d:32',
            extra={'vif_port_id': uuidutils.generate_uuid()})
        self.neutron_port = {'id': '132f871f-eaec-4fed-9475-0d54465e0f00',
                             'mac_address': '52:54:00:cf:2d:32'}

    def test_init_incorrect_provisioning_net(self):
        self.config(provisioning_network_uuid=None, group='neutron')
        self.assertRaises(exception.DriverLoadError, neutron.NeutronNetwork)
        self.config(provisioning_network_uuid=uuidutils.generate_uuid(),
                    group='neutron')
        self.config(cleaning_network_uuid='asdf', group='neutron')
        self.assertRaises(exception.DriverLoadError, neutron.NeutronNetwork)

    @mock.patch.object(neutron_common, 'add_ports_to_network')
    def test_add_provisioning_network(self, add_ports_mock):
        add_ports_mock.return_value = {self.port.uuid: self.neutron_port['id']}
        with task_manager.acquire(self.context, self.node.id) as task:
            self.interface.add_provisioning_network(task)
            add_ports_mock.assert_called_once_with(
                task, CONF.neutron.provisioning_network_uuid)
        self.port.refresh()
        self.assertEqual(self.neutron_port['id'],
                         self.port.internal_info['provisioning_vif_port_id'])

    @mock.patch.object(neutron_common, 'remove_ports_from_network')
    def test_remove_provisioning_network(self, remove_ports_mock):
        self.port.internal_info = {'provisioning_vif_port_id': 'vif-port-id'}
        self.port.save()
        with task_manager.acquire(self.context, self.node.id) as task:
            self.interface.remove_provisioning_network(task)
            remove_ports_mock.assert_called_once_with(
                task, CONF.neutron.provisioning_network_uuid)
        self.port.refresh()
        self.assertNotIn('provisioning_vif_port_id', self.port.internal_info)

    @mock.patch.object(neutron_common, 'rollback_ports')
    @mock.patch.object(neutron_common, 'add_ports_to_network')
    def test_add_cleaning_network(self, add_ports_mock, rollback_mock):
        add_ports_mock.return_value = {self.port.uuid: self.neutron_port['id']}
        with task_manager.acquire(self.context, self.node.id) as task:
            res = self.interface.add_cleaning_network(task)
            rollback_mock.assert_called_once_with(
                task, CONF.neutron.cleaning_network_uuid)
            self.assertEqual(res, add_ports_mock.return_value)
        self.port.refresh()
        self.assertEqual(self.neutron_port['id'],
                         self.port.internal_info['cleaning_vif_port_id'])

    @mock.patch.object(neutron_common, 'remove_ports_from_network')
    def test_remove_cleaning_network(self, remove_ports_mock):
        self.port.internal_info = {'cleaning_vif_port_id': 'vif-port-id'}
        self.port.save()
        with task_manager.acquire(self.context, self.node.id) as task:
            self.interface.remove_cleaning_network(task)
            remove_ports_mock.assert_called_once_with(
                task, CONF.neutron.cleaning_network_uuid)
        self.port.refresh()
        self.assertNotIn('cleaning_vif_port_id', self.port.internal_info)

    @mock.patch.object(neutron_common, 'remove_neutron_ports')
    def test_unconfigure_tenant_networks(self, remove_ports_mock):
        with task_manager.acquire(self.context, self.node.id) as task:
            self.interface.unconfigure_tenant_networks(task)
            remove_ports_mock.assert_called_once_with(
                task, {'device_id': task.node.uuid})

    def test_configure_tenant_networks_no_ports_for_node(self):
        n = utils.create_test_node(self.context, network_interface='neutron',
                                   uuid=uuidutils.generate_uuid())
        with task_manager.acquire(self.context, n.id) as task:
            self.assertRaisesRegexp(
                exception.NetworkError, 'No ports are associated',
                self.interface.configure_tenant_networks, task)

    @mock.patch.object(neutron_common, 'get_client')
    @mock.patch.object(neutron, 'LOG')
    def test_configure_tenant_networks_no_vif_id(self, log_mock, client_mock):
        self.port.extra = {}
        self.port.save()
        with task_manager.acquire(self.context, self.node.id) as task:
            self.interface.configure_tenant_networks(task)
            client_mock.assert_called_once_with(task.context.auth_token)
        self.assertIn('no vif_port_id value in extra',
                      log_mock.warning.call_args[0][0])

    @mock.patch.object(neutron_common, 'get_client')
    def test_configure_tenant_networks_update_fail(self, client_mock):
        client = client_mock.return_value
        client.update_port.side_effect = neutron_exceptions.ConnectionFailed(
            reason='meow')
        with task_manager.acquire(self.context, self.node.id) as task:
            self.assertRaisesRegexp(
                exception.NetworkError, 'Could not add',
                self.interface.configure_tenant_networks, task)
            client_mock.assert_called_once_with(task.context.auth_token)

    @mock.patch.object(neutron_common, 'get_client')
    def _test_configure_tenant_networks(self, client_mock, is_client_id=False):
        upd_mock = mock.Mock()
        client_mock.return_value.update_port = upd_mock
        second_port = utils.create_test_port(
            self.context, node_id=self.node.id, address='52:54:00:cf:2d:33',
            extra={'vif_port_id': uuidutils.generate_uuid()},
            uuid=uuidutils.generate_uuid(),
            local_link_connection={'switch_id': '0a:1b:2c:3d:4e:ff',
                                   'port_id': 'Ethernet1/1',
                                   'switch_info': 'switch2'}
        )
        if is_client_id:
            client_ids = (CLIENT_ID1, CLIENT_ID2)
            ports = (self.port, second_port)
            for port, client_id in zip(ports, client_ids):
                extra = port.extra
                extra['client-id'] = client_id
                port.extra = extra
                port.save()

        expected_body = {
            'port': {
                'device_owner': 'baremetal:none',
                'device_id': self.node.instance_uuid or self.node.uuid,
                'admin_state_up': True,
                'binding:vnic_type': 'baremetal',
                'binding:host_id': self.node.uuid,
            }
        }
        port1_body = copy.deepcopy(expected_body)
        port1_body['port']['binding:profile'] = {
            'local_link_information': [self.port.local_link_connection]
        }
        port2_body = copy.deepcopy(expected_body)
        port2_body['port']['binding:profile'] = {
            'local_link_information': [second_port.local_link_connection]
        }
        if is_client_id:
            port1_body['port']['extra_dhcp_opts'] = (
                [{'opt_name': 'client-id', 'opt_value': client_ids[0]}])
            port2_body['port']['extra_dhcp_opts'] = (
                [{'opt_name': 'client-id', 'opt_value': client_ids[1]}])
        with task_manager.acquire(self.context, self.node.id) as task:
            self.interface.configure_tenant_networks(task)
            client_mock.assert_called_once_with(task.context.auth_token)
        upd_mock.assert_has_calls(
            [mock.call(self.port.extra['vif_port_id'], port1_body),
             mock.call(second_port.extra['vif_port_id'], port2_body)],
            any_order=True
        )

    def test_configure_tenant_networks(self):
        self.node.instance_uuid = uuidutils.generate_uuid()
        self.node.save()
        self._test_configure_tenant_networks()

    def test_configure_tenant_networks_no_instance_uuid(self):
        self._test_configure_tenant_networks()

    def test_configure_tenant_networks_with_client_id(self):
        self.node.instance_uuid = uuidutils.generate_uuid()
        self.node.save()
        self._test_configure_tenant_networks(is_client_id=True)

    @mock.patch.object(neutron_common, 'get_client')
    def test_configure_tenant_networks_with_portgroups(self, client_mock):
        pg = utils.create_test_portgroup(
            self.context, node_id=self.node.id, address='ff:54:00:cf:2d:32',
            extra={'vif_port_id': uuidutils.generate_uuid()})
        port1 = utils.create_test_port(
            self.context, node_id=self.node.id, address='ff:54:00:cf:2d:33',
            uuid=uuidutils.generate_uuid(),
            portgroup_id=pg.id,
            local_link_connection={'switch_id': '0a:1b:2c:3d:4e:ff',
                                   'port_id': 'Ethernet1/1',
                                   'switch_info': 'switch2'}
        )
        port2 = utils.create_test_port(
            self.context, node_id=self.node.id, address='ff:54:00:cf:2d:34',
            uuid=uuidutils.generate_uuid(),
            portgroup_id=pg.id,
            local_link_connection={'switch_id': '0a:1b:2c:3d:4e:ff',
                                   'port_id': 'Ethernet1/2',
                                   'switch_info': 'switch2'}
        )
        upd_mock = mock.Mock()
        client_mock.return_value.update_port = upd_mock
        expected_body = {
            'port': {
                'device_owner': 'baremetal:none',
                'device_id': self.node.uuid,
                'admin_state_up': True,
                'binding:vnic_type': 'baremetal',
                'binding:host_id': self.node.uuid,
            }
        }
        call1_body = copy.deepcopy(expected_body)
        call1_body['port']['binding:profile'] = {
            'local_link_information': [self.port.local_link_connection]
        }
        call2_body = copy.deepcopy(expected_body)
        call2_body['port']['binding:profile'] = {
            'local_link_information': [port1.local_link_connection,
                                       port2.local_link_connection]
        }
        with task_manager.acquire(self.context, self.node.id) as task:
            self.interface.configure_tenant_networks(task)
            client_mock.assert_called_once_with(task.context.auth_token)
        upd_mock.assert_has_calls(
            [mock.call(self.port.extra['vif_port_id'], call1_body),
             mock.call(pg.extra['vif_port_id'], call2_body)]
        )
