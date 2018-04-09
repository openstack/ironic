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
VIFMIXINPATH = 'ironic.drivers.modules.network.common.NeutronVIFPortIDMixin'


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

    def test_init_incorrect_provisioning_net(self):
        self.config(provisioning_network=None, group='neutron')
        self.assertRaises(exception.DriverLoadError, neutron.NeutronNetwork)
        self.config(provisioning_network=uuidutils.generate_uuid(),
                    group='neutron')
        self.config(cleaning_network=None, group='neutron')
        self.assertRaises(exception.DriverLoadError, neutron.NeutronNetwork)

    @mock.patch.object(neutron_common, 'validate_network', autospec=True)
    def test_validate(self, validate_mock):
        with task_manager.acquire(self.context, self.node.id) as task:
            self.interface.validate(task)
        self.assertEqual([mock.call(CONF.neutron.cleaning_network,
                                    'cleaning network'),
                          mock.call(CONF.neutron.provisioning_network,
                                    'provisioning network')],
                         validate_mock.call_args_list)

    @mock.patch.object(neutron_common, 'validate_network',
                       side_effect=lambda n, t: n)
    @mock.patch.object(neutron_common, 'rollback_ports')
    @mock.patch.object(neutron_common, 'add_ports_to_network')
    def test_add_provisioning_network(self, add_ports_mock, rollback_mock,
                                      validate_mock):
        self.port.internal_info = {'provisioning_vif_port_id': 'vif-port-id'}
        self.port.save()
        add_ports_mock.return_value = {self.port.uuid: self.neutron_port['id']}
        with task_manager.acquire(self.context, self.node.id) as task:
            self.interface.add_provisioning_network(task)
            rollback_mock.assert_called_once_with(
                task, CONF.neutron.provisioning_network)
            add_ports_mock.assert_called_once_with(
                task, CONF.neutron.provisioning_network,
                security_groups=[])
            validate_mock.assert_called_once_with(
                CONF.neutron.provisioning_network,
                'provisioning network')
        self.port.refresh()
        self.assertEqual(self.neutron_port['id'],
                         self.port.internal_info['provisioning_vif_port_id'])

    @mock.patch.object(neutron_common, 'validate_network',
                       lambda n, t: n)
    @mock.patch.object(neutron_common, 'rollback_ports')
    @mock.patch.object(neutron_common, 'add_ports_to_network')
    def test_add_provisioning_network_with_sg(self, add_ports_mock,
                                              rollback_mock):
        sg_ids = []
        for i in range(2):
            sg_ids.append(uuidutils.generate_uuid())

        self.config(provisioning_network_security_groups=sg_ids,
                    group='neutron')
        add_ports_mock.return_value = {self.port.uuid: self.neutron_port['id']}
        with task_manager.acquire(self.context, self.node.id) as task:
            self.interface.add_provisioning_network(task)
            rollback_mock.assert_called_once_with(
                task, CONF.neutron.provisioning_network)
            add_ports_mock.assert_called_once_with(
                task, CONF.neutron.provisioning_network,
                security_groups=(
                    CONF.neutron.provisioning_network_security_groups))
        self.port.refresh()
        self.assertEqual(self.neutron_port['id'],
                         self.port.internal_info['provisioning_vif_port_id'])

    @mock.patch.object(neutron_common, 'validate_network',
                       side_effect=lambda n, t: n)
    @mock.patch.object(neutron_common, 'remove_ports_from_network')
    def test_remove_provisioning_network(self, remove_ports_mock,
                                         validate_mock):
        self.port.internal_info = {'provisioning_vif_port_id': 'vif-port-id'}
        self.port.save()
        with task_manager.acquire(self.context, self.node.id) as task:
            self.interface.remove_provisioning_network(task)
            remove_ports_mock.assert_called_once_with(
                task, CONF.neutron.provisioning_network)
            validate_mock.assert_called_once_with(
                CONF.neutron.provisioning_network,
                'provisioning network')
        self.port.refresh()
        self.assertNotIn('provisioning_vif_port_id', self.port.internal_info)

    @mock.patch.object(neutron_common, 'validate_network',
                       side_effect=lambda n, t: n)
    @mock.patch.object(neutron_common, 'rollback_ports')
    @mock.patch.object(neutron_common, 'add_ports_to_network')
    def test_add_cleaning_network(self, add_ports_mock, rollback_mock,
                                  validate_mock):
        add_ports_mock.return_value = {self.port.uuid: self.neutron_port['id']}
        with task_manager.acquire(self.context, self.node.id) as task:
            res = self.interface.add_cleaning_network(task)
            rollback_mock.assert_called_once_with(
                task, CONF.neutron.cleaning_network)
            self.assertEqual(res, add_ports_mock.return_value)
            validate_mock.assert_called_once_with(
                CONF.neutron.cleaning_network,
                'cleaning network')
        self.port.refresh()
        self.assertEqual(self.neutron_port['id'],
                         self.port.internal_info['cleaning_vif_port_id'])

    @mock.patch.object(neutron_common, 'validate_network',
                       lambda n, t: n)
    @mock.patch.object(neutron_common, 'rollback_ports')
    @mock.patch.object(neutron_common, 'add_ports_to_network')
    def test_add_cleaning_network_with_sg(self, add_ports_mock, rollback_mock):
        add_ports_mock.return_value = {self.port.uuid: self.neutron_port['id']}
        sg_ids = []
        for i in range(2):
            sg_ids.append(uuidutils.generate_uuid())
        self.config(cleaning_network_security_groups=sg_ids, group='neutron')
        with task_manager.acquire(self.context, self.node.id) as task:
            res = self.interface.add_cleaning_network(task)
            add_ports_mock.assert_called_once_with(
                task, CONF.neutron.cleaning_network,
                security_groups=CONF.neutron.cleaning_network_security_groups)
            rollback_mock.assert_called_once_with(
                task, CONF.neutron.cleaning_network)
            self.assertEqual(res, add_ports_mock.return_value)
        self.port.refresh()
        self.assertEqual(self.neutron_port['id'],
                         self.port.internal_info['cleaning_vif_port_id'])

    @mock.patch.object(neutron_common, 'validate_network',
                       side_effect=lambda n, t: n)
    @mock.patch.object(neutron_common, 'remove_ports_from_network')
    def test_remove_cleaning_network(self, remove_ports_mock,
                                     validate_mock):
        self.port.internal_info = {'cleaning_vif_port_id': 'vif-port-id'}
        self.port.save()
        with task_manager.acquire(self.context, self.node.id) as task:
            self.interface.remove_cleaning_network(task)
            remove_ports_mock.assert_called_once_with(
                task, CONF.neutron.cleaning_network)
            validate_mock.assert_called_once_with(
                CONF.neutron.cleaning_network,
                'cleaning network')
        self.port.refresh()
        self.assertNotIn('cleaning_vif_port_id', self.port.internal_info)

    @mock.patch.object(neutron_common, 'unbind_neutron_port')
    def test_unconfigure_tenant_networks(self, mock_unbind_port):
        with task_manager.acquire(self.context, self.node.id) as task:
            self.interface.unconfigure_tenant_networks(task)
            mock_unbind_port.assert_called_once_with(
                self.port.extra['vif_port_id'])

    def test_configure_tenant_networks_no_ports_for_node(self):
        n = utils.create_test_node(self.context, network_interface='neutron',
                                   uuid=uuidutils.generate_uuid())
        with task_manager.acquire(self.context, n.id) as task:
            self.assertRaisesRegex(
                exception.NetworkError, 'No ports are associated',
                self.interface.configure_tenant_networks, task)

    @mock.patch.object(neutron_common, 'get_client')
    @mock.patch.object(neutron, 'LOG')
    def test_configure_tenant_networks_no_vif_id(self, log_mock, client_mock):
        self.port.extra = {}
        self.port.save()
        upd_mock = mock.Mock()
        client_mock.return_value.update_port = upd_mock
        with task_manager.acquire(self.context, self.node.id) as task:
            self.assertRaisesRegex(exception.NetworkError,
                                   'No neutron ports or portgroups are '
                                   'associated with node',
                                   self.interface.configure_tenant_networks,
                                   task)
        client_mock.assert_called_once_with()
        upd_mock.assert_not_called()
        self.assertIn('No neutron ports or portgroups are associated with',
                      log_mock.error.call_args[0][0])

    @mock.patch.object(neutron_common, 'get_client')
    @mock.patch.object(neutron, 'LOG')
    def test_configure_tenant_networks_multiple_ports_one_vif_id(
            self, log_mock, client_mock):
        expected_body = {
            'port': {
                'binding:vnic_type': 'baremetal',
                'binding:host_id': self.node.uuid,
                'binding:profile': {'local_link_information':
                                    [self.port.local_link_connection]}
            }
        }
        utils.create_test_port(self.context, node_id=self.node.id,
                               address='52:54:00:cf:2d:33', extra={},
                               uuid=uuidutils.generate_uuid())
        upd_mock = mock.Mock()
        client_mock.return_value.update_port = upd_mock
        with task_manager.acquire(self.context, self.node.id) as task:
            self.interface.configure_tenant_networks(task)
        client_mock.assert_called_once_with()
        upd_mock.assert_called_once_with(self.port.extra['vif_port_id'],
                                         expected_body)

    @mock.patch.object(neutron_common, 'get_client')
    def test_configure_tenant_networks_update_fail(self, client_mock):
        client = client_mock.return_value
        client.update_port.side_effect = neutron_exceptions.ConnectionFailed(
            reason='meow')
        with task_manager.acquire(self.context, self.node.id) as task:
            self.assertRaisesRegex(
                exception.NetworkError, 'Could not add',
                self.interface.configure_tenant_networks, task)
            client_mock.assert_called_once_with()

    @mock.patch.object(neutron_common, 'get_client')
    def _test_configure_tenant_networks(self, client_mock, is_client_id=False,
                                        vif_int_info=False):
        upd_mock = mock.Mock()
        client_mock.return_value.update_port = upd_mock
        if vif_int_info:
            kwargs = {'internal_info': {
                'tenant_vif_port_id': uuidutils.generate_uuid()}}
            self.port.internal_info = {
                'tenant_vif_port_id': self.port.extra['vif_port_id']}
            self.port.extra = {}
        else:
            kwargs = {'extra': {'vif_port_id': uuidutils.generate_uuid()}}
        second_port = utils.create_test_port(
            self.context, node_id=self.node.id, address='52:54:00:cf:2d:33',
            uuid=uuidutils.generate_uuid(),
            local_link_connection={'switch_id': '0a:1b:2c:3d:4e:ff',
                                   'port_id': 'Ethernet1/1',
                                   'switch_info': 'switch2'},
            **kwargs
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
                [{'opt_name': '61', 'opt_value': client_ids[0]}])
            port2_body['port']['extra_dhcp_opts'] = (
                [{'opt_name': '61', 'opt_value': client_ids[1]}])
        with task_manager.acquire(self.context, self.node.id) as task:
            self.interface.configure_tenant_networks(task)
            client_mock.assert_called_once_with()
        if vif_int_info:
            portid1 = self.port.internal_info['tenant_vif_port_id']
            portid2 = second_port.internal_info['tenant_vif_port_id']
        else:
            portid1 = self.port.extra['vif_port_id']
            portid2 = second_port.extra['vif_port_id']
        upd_mock.assert_has_calls(
            [mock.call(portid1, port1_body),
             mock.call(portid2, port2_body)],
            any_order=True
        )

    def test_configure_tenant_networks_vif_extra(self):
        self.node.instance_uuid = uuidutils.generate_uuid()
        self.node.save()
        self._test_configure_tenant_networks()

    def test_configure_tenant_networks_vif_int_info(self):
        self.node.instance_uuid = uuidutils.generate_uuid()
        self.node.save()
        self._test_configure_tenant_networks(vif_int_info=True)

    def test_configure_tenant_networks_no_instance_uuid(self):
        self._test_configure_tenant_networks()

    def test_configure_tenant_networks_with_client_id(self):
        self.node.instance_uuid = uuidutils.generate_uuid()
        self.node.save()
        self._test_configure_tenant_networks(is_client_id=True)

    @mock.patch.object(neutron_common, 'get_client', autospec=True)
    @mock.patch.object(neutron_common, 'get_local_group_information',
                       autospec=True)
    def test_configure_tenant_networks_with_portgroups(
            self, glgi_mock, client_mock):
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
        local_group_info = {'a': 'b'}
        glgi_mock.return_value = local_group_info
        expected_body = {
            'port': {
                'binding:vnic_type': 'baremetal',
                'binding:host_id': self.node.uuid,
            }
        }
        call1_body = copy.deepcopy(expected_body)
        call1_body['port']['binding:profile'] = {
            'local_link_information': [self.port.local_link_connection],
        }
        call2_body = copy.deepcopy(expected_body)
        call2_body['port']['binding:profile'] = {
            'local_link_information': [port1.local_link_connection,
                                       port2.local_link_connection],
            'local_group_information': local_group_info
        }
        with task_manager.acquire(self.context, self.node.id) as task:
            # Override task.portgroups here, to have ability to check
            # that mocked get_local_group_information was called with
            # this portgroup object.
            task.portgroups = [pg]
            self.interface.configure_tenant_networks(task)
            client_mock.assert_called_once_with()
            glgi_mock.assert_called_once_with(task, pg)
        upd_mock.assert_has_calls(
            [mock.call(self.port.extra['vif_port_id'], call1_body),
             mock.call(pg.extra['vif_port_id'], call2_body)]
        )
