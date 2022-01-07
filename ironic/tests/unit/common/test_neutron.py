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
import json
import os
import time
from unittest import mock

from keystoneauth1 import loading as ks_loading
import openstack
from openstack.connection import exceptions as openstack_exc
from oslo_utils import uuidutils

from ironic.common import context
from ironic.common import exception
from ironic.common import neutron
from ironic.conductor import task_manager
from ironic.tests import base
from ironic.tests.unit.db import base as db_base
from ironic.tests.unit.objects import utils as object_utils
from ironic.tests.unit import stubs


@mock.patch('ironic.common.keystone.get_service_auth', autospec=True,
            return_value=mock.sentinel.sauth)
@mock.patch('ironic.common.keystone.get_auth', autospec=True,
            return_value=mock.sentinel.auth)
@mock.patch('ironic.common.keystone.get_adapter', autospec=True)
@mock.patch('ironic.common.keystone.get_session', autospec=True,
            return_value=mock.sentinel.session)
@mock.patch.object(openstack.connection, "Connection", autospec=True)
class TestNeutronClient(base.TestCase):

    def setUp(self):
        super(TestNeutronClient, self).setUp()
        # NOTE(pas-ha) register keystoneauth dynamic options manually
        plugin = ks_loading.get_plugin_loader('password')
        opts = ks_loading.get_auth_plugin_conf_options(plugin)
        self.cfg_fixture.register_opts(opts, group='neutron')
        self.config(retries=2,
                    group='neutron')
        self.config(username='test-admin-user',
                    project_name='test-admin-tenant',
                    password='test-admin-password',
                    auth_url='test-auth-uri',
                    auth_type='password',
                    interface='internal',
                    service_type='network',
                    timeout=10,
                    group='neutron')
        # force-reset the global session object
        neutron._NEUTRON_SESSION = None
        self.context = context.RequestContext(global_request_id='global')

    def _call_and_assert_client(self, client_mock, url,
                                auth=mock.sentinel.auth):
        neutron.get_client(context=self.context)
        client_mock.assert_called_once_with(oslo_conf=mock.ANY,
                                            session=mock.sentinel.session)

    @mock.patch('ironic.common.context.RequestContext', autospec=True)
    def test_get_neutron_client_with_token(self, mock_ctxt, mock_client_init,
                                           mock_session, mock_adapter,
                                           mock_auth, mock_sauth):
        mock_ctxt.return_value = ctxt = mock.Mock()
        ctxt.auth_token = 'test-token-123'
        neutron.get_client(token='test-token-123')
        mock_ctxt.assert_called_once_with(auth_token='test-token-123')
        mock_client_init.assert_called_once_with(oslo_conf=mock.ANY,
                                                 session=mock.sentinel.session)

        # testing handling of default url_timeout
        mock_session.assert_has_calls(
            [mock.call('neutron', timeout=10),
             mock.call('neutron', auth=mock.sentinel.sauth, timeout=10)])

    def test_get_neutron_client_with_context(self, mock_client_init,
                                             mock_session, mock_adapter,
                                             mock_auth, mock_sauth):
        self.context = context.RequestContext(global_request_id='global',
                                              auth_token='test-token-123')
        self._call_and_assert_client(mock_client_init, 'neutron_url')
        # testing handling of default url_timeout
        mock_session.assert_has_calls(
            [mock.call('neutron', timeout=10),
             mock.call('neutron', auth=mock.sentinel.sauth, timeout=10)])

    def test_get_neutron_client_without_token(self, mock_client_init,
                                              mock_session, mock_adapter,
                                              mock_auth, mock_sauth):
        self._call_and_assert_client(mock_client_init, 'neutron_url')
        mock_session.assert_has_calls(
            [mock.call('neutron', timeout=10),
             mock.call('neutron', auth=mock.sentinel.auth, timeout=10)])

    def test_get_neutron_client_noauth(self, mock_client_init, mock_session,
                                       mock_adapter, mock_auth, mock_sauth):
        self.config(endpoint_override='neutron_url',
                    auth_type='none',
                    timeout=10,
                    group='neutron')

        self._call_and_assert_client(mock_client_init, 'neutron_url')

        self.assertEqual('none', neutron.CONF.neutron.auth_type)
        mock_session.assert_has_calls(
            [mock.call('neutron', timeout=10),
             mock.call('neutron', auth=mock.sentinel.auth, timeout=10)])

    def test_get_neutron_client_auth_from_config(self, mock_client_init,
                                                 mock_session, mock_adapter,
                                                 mock_auth, mock_sauth):
        self.context = context.RequestContext(global_request_id='global',
                                              auth_token='test-token-123')
        neutron.get_client(context=self.context, auth_from_config=True)
        mock_client_init.assert_called_once_with(oslo_conf=mock.ANY,
                                                 session=mock.sentinel.session)
        mock_sauth.assert_not_called()
        # testing handling of default url_timeout
        mock_session.assert_has_calls(
            [mock.call('neutron', timeout=10),
             mock.call('neutron', auth=mock.sentinel.auth, timeout=10)])


class TestUpdateNeutronPort(base.TestCase):
    def setUp(self):
        super(TestUpdateNeutronPort, self).setUp()

        self.uuid = uuidutils.generate_uuid()
        self.context = context.RequestContext()
        self.port_attr = {'name': 'name_it'}

    @mock.patch.object(neutron, 'get_client', autospec=True)
    def test_update_neutron_port(self, client_mock):
        client_mock.return_value.get_port.return_value = {}
        client_mock.return_value.update_port.return_value = {'name': 'name_it'}

        neutron.update_neutron_port(self.context, self.uuid, self.port_attr)

        client_mock.assert_any_call(context=self.context)
        client_mock.assert_any_call(context=self.context,
                                    auth_from_config=True)
        client_mock.return_value.get_port.assert_called_once_with(self.uuid)
        client_mock.return_value.update_port.assert_called_once_with(
            self.uuid, **self.port_attr)

    @mock.patch.object(neutron, 'get_client', autospec=True)
    def test_update_neutron_port_with_client(self, client_mock):
        client_mock.return_value.get_port.return_value = {}
        client_mock.return_value.update_port.return_value = {
            'name': 'name_it'}
        client = mock.Mock()
        client.update_port.return_value = {}

        neutron.update_neutron_port(self.context, self.uuid, self.port_attr,
                                    client)

        self.assertFalse(client_mock.called)
        client.update_port.assert_called_once_with(self.uuid, **self.port_attr)

    @mock.patch.object(neutron, 'get_client', autospec=True)
    def test_update_neutron_port_with_exception(self, client_mock):
        client_mock.return_value.get_port.side_effect = \
            openstack_exc.OpenStackCloudException
        client_mock.return_value.update_port.return_value = {}

        self.assertRaises(
            openstack_exc.OpenStackCloudException,
            neutron.update_neutron_port,
            self.context, self.uuid, self.port_attr)

        client_mock.assert_called_once_with(context=self.context)
        client_mock.return_value.get_port.assert_called_once_with(self.uuid)


class TestNeutronNetworkActions(db_base.DbTestCase):

    _CLIENT_ID = (
        '20:00:55:04:01:fe:80:00:00:00:00:00:00:00:02:c9:02:00:23:13:92')

    def setUp(self):
        super(TestNeutronNetworkActions, self).setUp()
        self.node = object_utils.create_test_node(self.context)
        self.ports = [object_utils.create_test_port(
            self.context, node_id=self.node.id,
            uuid='1be26c0b-03f2-4d2e-ae87-c02d7f33c782',
            address='52:54:00:cf:2d:32',
            extra={'vif_port_id': uuidutils.generate_uuid()}
        )]
        self.neutron_port = stubs.FakeNeutronPort(
            id='132f871f-eaec-4fed-9475-0d54465e0f00',
            mac_address='52:54:00:cf:2d:32',
            fixed_ips=[])

        self.network_uuid = uuidutils.generate_uuid()
        self.client_mock = mock.Mock()
        patcher = mock.patch('ironic.common.neutron.get_client',
                             return_value=self.client_mock, autospec=True)
        patcher.start()
        self.addCleanup(patcher.stop)

        port_show_file = os.path.join(
            os.path.dirname(__file__), 'json_samples',
            'neutron_port_show.json')
        with open(port_show_file, 'rb') as fl:
            self.port_data = json.load(fl)

        self.client_mock.get_port.return_value = stubs.FakeNeutronPort(
            **self.port_data['port'])

        network_show_file = os.path.join(
            os.path.dirname(__file__), 'json_samples',
            'neutron_network_show.json')
        with open(network_show_file, 'rb') as fl:
            self.network_data = json.load(fl)

        self.client_mock.get_network.return_value = stubs.FakeNeutronNetwork(
            **self.network_data['network'])

        subnet_show_file = os.path.join(
            os.path.dirname(__file__), 'json_samples',
            'neutron_subnet_show.json')
        with open(subnet_show_file, 'rb') as fl:
            self.subnet_data = json.load(fl)

        self.client_mock.get_subnet.return_value = stubs.FakeNeutronSubnet(
            **self.subnet_data['subnet'])

    @mock.patch.object(neutron, 'update_neutron_port', autospec=True)
    def _test_add_ports_to_network(self, update_mock, is_client_id,
                                   security_groups=None,
                                   add_all_ports=False):
        # Ports will be created only if pxe_enabled is True
        self.node.network_interface = 'neutron'
        self.node.save()
        port2 = object_utils.create_test_port(
            self.context, node_id=self.node.id,
            uuid=uuidutils.generate_uuid(),
            address='54:00:00:cf:2d:22',
            pxe_enabled=False
        )
        if add_all_ports:
            self.config(add_all_ports=True, group="neutron")
        port = self.ports[0]
        if is_client_id:
            extra = port.extra
            extra['client-id'] = self._CLIENT_ID
            port.extra = extra
            port.save()
        expected_create_attrs = {
            'network_id': self.network_uuid,
            'admin_state_up': True,
            'binding:vnic_type': 'baremetal',
            'device_id': self.node.uuid
        }
        expected_update_attrs = {
            'device_owner': 'baremetal:none',
            'binding:host_id': self.node.uuid,
            'mac_address': port.address,
            'binding:profile': {
                'local_link_information': [port.local_link_connection]
            }
        }
        if security_groups:
            expected_create_attrs['security_groups'] = security_groups

        if is_client_id:
            expected_create_attrs['extra_dhcp_opts'] = (
                [{'opt_name': '61', 'opt_value': self._CLIENT_ID}])

        if add_all_ports:
            expected_create_attrs2 = copy.deepcopy(expected_create_attrs)
            expected_update_attrs2 = copy.deepcopy(expected_update_attrs)
            expected_update_attrs2['mac_address'] = port2.address
            expected_create_attrs2['fixed_ips'] = []
            neutron_port2 = stubs.FakeNeutronPort(
                id='132f871f-eaec-4fed-9475-0d54465e0f01',
                mac_address=port2.address,
                fixed_ips=[])
            self.client_mock.create_port.side_effect = [self.neutron_port,
                                                        neutron_port2]
            update_mock.side_effect = [self.neutron_port, neutron_port2]
            expected = {port.uuid: self.neutron_port.id,
                        port2.uuid: neutron_port2.id}

        else:
            self.client_mock.create_port.return_value = self.neutron_port
            update_mock.return_value = self.neutron_port
            expected = {port.uuid: self.neutron_port['id']}

        with task_manager.acquire(self.context, self.node.uuid) as task:
            ports = neutron.add_ports_to_network(
                task, self.network_uuid, security_groups=security_groups)
            self.assertEqual(expected, ports)
            if add_all_ports:
                create_calls = [mock.call(**expected_create_attrs),
                                mock.call(**expected_create_attrs2)]
                update_calls = [
                    mock.call(self.context, self.neutron_port['id'],
                              expected_update_attrs),
                    mock.call(self.context, neutron_port2['id'],
                              expected_update_attrs2)]
                self.client_mock.create_port.assert_has_calls(create_calls)
                update_mock.assert_has_calls(update_calls)
            else:
                self.client_mock.create_port.assert_called_once_with(
                    **expected_create_attrs)
                update_mock.assert_called_once_with(
                    self.context, self.neutron_port['id'],
                    expected_update_attrs)

    def test_add_ports_to_network(self):
        self._test_add_ports_to_network(is_client_id=False,
                                        security_groups=None)

    def test_add_ports_to_network_all_ports(self):
        self._test_add_ports_to_network(is_client_id=False,
                                        security_groups=None,
                                        add_all_ports=True)

    @mock.patch.object(neutron, '_verify_security_groups', autospec=True)
    def test_add_ports_to_network_with_sg(self, verify_mock):
        sg_ids = []
        for i in range(2):
            sg_ids.append(uuidutils.generate_uuid())
        self._test_add_ports_to_network(is_client_id=False,
                                        security_groups=sg_ids)

    @mock.patch.object(neutron, 'update_neutron_port', autospec=True)
    def test__add_ip_addresses_for_ipv6_stateful(self, mock_update):
        subnet_id = uuidutils.generate_uuid()
        self.client_mock.get_subnet.return_value = stubs.FakeNeutronSubnet(
            id=subnet_id,
            ip_version=6,
            ipv6_address_mode='dhcpv6-stateful')
        self.neutron_port.fixed_ips = [{'subnet_id': subnet_id,
                                        'ip_address': '2001:db8::1'}]

        expected_body = {
            'fixed_ips': [
                {'subnet_id': subnet_id, 'ip_address': '2001:db8::1'},
                {'subnet_id': subnet_id},
                {'subnet_id': subnet_id},
                {'subnet_id': subnet_id}
            ]
        }

        neutron._add_ip_addresses_for_ipv6_stateful(
            self.context, self.neutron_port, self.client_mock)
        mock_update.assert_called_once_with(
            self.context, self.neutron_port.id, expected_body,
            client=self.client_mock)

    def test_verify_sec_groups(self):
        sg_ids = []
        expected_vals = []
        for i in range(2):
            uuid = uuidutils.generate_uuid()
            sg_ids.append(uuid)
            expected_vals.append(stubs.FakeNeutronSecurityGroup(id=uuid))

        client = mock.MagicMock()
        client.security_groups.return_value = iter(expected_vals)

        self.assertIsNone(
            neutron._verify_security_groups(sg_ids, client))
        client.security_groups.assert_called_once_with(id=sg_ids)

    def test_verify_sec_groups_less_than_configured(self):
        sg_ids = []
        expected_vals = []
        for i in range(2):
            uuid = uuidutils.generate_uuid()
            sg_ids.append(uuid)
            expected_vals.append(stubs.FakeNeutronSecurityGroup(id=uuid))

        client = mock.MagicMock()
        client.security_groups.return_value = iter(expected_vals)

        self.assertIsNone(
            neutron._verify_security_groups(sg_ids[:1], client))
        client.security_groups.assert_called_once_with(id=sg_ids[:1])

    def test_verify_sec_groups_more_than_configured(self):
        sg_ids = []
        for i in range(1):
            sg_ids.append(uuidutils.generate_uuid())

        client = mock.MagicMock()
        client.get.return_value = iter([])

        self.assertRaises(
            exception.NetworkError,
            neutron._verify_security_groups, sg_ids, client)
        client.security_groups.assert_called_once_with(id=sg_ids)

    def test_verify_sec_groups_no_sg_from_neutron(self):
        sg_ids = []
        for i in range(1):
            sg_ids.append(uuidutils.generate_uuid())

        client = mock.MagicMock()
        client.security_groups.return_value = iter([])

        self.assertRaises(
            exception.NetworkError,
            neutron._verify_security_groups, sg_ids, client)
        client.security_groups.assert_called_once_with(id=sg_ids)

    def test_verify_sec_groups_exception_by_neutronclient(self):
        sg_ids = []
        for i in range(2):
            sg_ids.append(uuidutils.generate_uuid())

        client = mock.MagicMock()
        client.security_groups.side_effect = (
            openstack_exc.OpenStackCloudException)

        self.assertRaisesRegex(
            exception.NetworkError,
            "Could not retrieve security groups",
            neutron._verify_security_groups, sg_ids, client)
        client.security_groups.assert_called_once_with(id=sg_ids)

    def test_add_ports_with_client_id_to_network(self):
        self._test_add_ports_to_network(is_client_id=True)

    @mock.patch.object(neutron, 'update_neutron_port', autospec=True)
    @mock.patch.object(neutron, 'validate_port_info', autospec=True)
    def test_add_ports_to_network_instance_uuid(self, vpi_mock, update_mock):
        self.node.instance_uuid = uuidutils.generate_uuid()
        self.node.network_interface = 'neutron'
        self.node.save()
        port = self.ports[0]
        expected_create_body = {
            'network_id': self.network_uuid,
            'admin_state_up': True,
            'binding:vnic_type': 'baremetal',
            'device_id': self.node.instance_uuid
        }
        expected_update_body = {
            'device_owner': 'baremetal:none',
            'binding:host_id': self.node.uuid,
            'mac_address': port.address,
            'binding:profile': {
                'local_link_information': [port.local_link_connection]
            }
        }
        vpi_mock.return_value = True
        # Ensure we can create ports
        self.client_mock.create_port.return_value = self.neutron_port
        update_mock.return_value = self.neutron_port
        expected = {port.uuid: self.neutron_port.id}
        with task_manager.acquire(self.context, self.node.uuid) as task:
            ports = neutron.add_ports_to_network(task, self.network_uuid)
            self.assertEqual(expected, ports)
            self.client_mock.create_port.assert_called_once_with(
                **expected_create_body)
            update_mock.assert_called_once_with(self.context,
                                                self.neutron_port['id'],
                                                expected_update_body)
        self.assertTrue(vpi_mock.called)

    @mock.patch.object(neutron, 'rollback_ports', autospec=True)
    def test_add_network_all_ports_fail(self, rollback_mock):
        # Check that if creating a port fails, the ports are cleaned up
        self.client_mock.create_port.side_effect = \
            openstack_exc.OpenStackCloudException

        with task_manager.acquire(self.context, self.node.uuid) as task:
            self.assertRaises(
                exception.NetworkError, neutron.add_ports_to_network, task,
                self.network_uuid)
            rollback_mock.assert_called_once_with(task, self.network_uuid)

    @mock.patch.object(neutron, 'update_neutron_port', autospec=True)
    @mock.patch.object(neutron, 'LOG', autospec=True)
    def test_add_network_create_some_ports_fail(self, log_mock, update_mock):
        object_utils.create_test_port(
            self.context, node_id=self.node.id,
            uuid=uuidutils.generate_uuid(),
            address='52:54:55:cf:2d:32',
            extra={'vif_port_id': uuidutils.generate_uuid()}
        )
        self.client_mock.create_port.side_effect = [
            self.neutron_port, openstack_exc.OpenStackCloudException]
        update_mock.return_value = self.neutron_port
        with task_manager.acquire(self.context, self.node.uuid) as task:
            neutron.add_ports_to_network(task, self.network_uuid)
            self.assertIn("Could not create neutron port for node's",
                          log_mock.warning.call_args_list[0][0][0])
            self.assertIn("Some errors were encountered when updating",
                          log_mock.warning.call_args_list[1][0][0])

    def test_add_network_no_port(self):
        # No port registered
        node = object_utils.create_test_node(self.context,
                                             uuid=uuidutils.generate_uuid())
        with task_manager.acquire(self.context, node.uuid) as task:
            self.assertEqual([], task.ports)
            self.assertRaisesRegex(exception.NetworkError, 'No available',
                                   neutron.add_ports_to_network,
                                   task, self.network_uuid)

    def test_add_network_no_pxe_enabled_ports(self):
        # Have port but no PXE enabled
        port = self.ports[0]
        port.pxe_enabled = False
        port.save()
        with task_manager.acquire(self.context, self.node.uuid) as task:
            self.assertFalse(task.ports[0].pxe_enabled)
            self.assertRaisesRegex(exception.NetworkError, 'No available',
                                   neutron.add_ports_to_network,
                                   task, self.network_uuid)

    @mock.patch.object(neutron, 'remove_neutron_ports', autospec=True)
    def test_remove_ports_from_network(self, remove_mock):
        with task_manager.acquire(self.context, self.node.uuid) as task:
            neutron.remove_ports_from_network(task, self.network_uuid)
            remove_mock.assert_called_once_with(
                task,
                {'network_id': self.network_uuid,
                 'mac_address': [self.ports[0].address]}
            )

    @mock.patch.object(neutron, 'remove_neutron_ports', autospec=True)
    def test_remove_ports_from_network_not_all_pxe_enabled(self, remove_mock):
        object_utils.create_test_port(
            self.context, node_id=self.node.id,
            uuid=uuidutils.generate_uuid(),
            address='52:54:55:cf:2d:32',
            pxe_enabled=False
        )
        with task_manager.acquire(self.context, self.node.uuid) as task:
            neutron.remove_ports_from_network(task, self.network_uuid)
            remove_mock.assert_called_once_with(
                task,
                {'network_id': self.network_uuid,
                 'mac_address': [self.ports[0].address]}
            )

    @mock.patch.object(neutron, 'remove_neutron_ports', autospec=True)
    def test_remove_ports_from_network_not_all_pxe_enabled_all_ports(
            self, remove_mock):
        self.config(add_all_ports=True, group="neutron")
        object_utils.create_test_port(
            self.context, node_id=self.node.id,
            uuid=uuidutils.generate_uuid(),
            address='52:54:55:cf:2d:32',
            pxe_enabled=False
        )
        with task_manager.acquire(self.context, self.node.uuid) as task:
            neutron.remove_ports_from_network(task, self.network_uuid)
            calls = [
                mock.call(task, {'network_id': self.network_uuid,
                                 'mac_address': [task.ports[0].address,
                                                 task.ports[1].address]}),
            ]
            remove_mock.assert_has_calls(calls)

    def test_remove_neutron_ports(self):
        with task_manager.acquire(self.context, self.node.uuid) as task:
            self.client_mock.ports.return_value = iter([self.neutron_port])
            neutron.remove_neutron_ports(task, {'param': 'value'})
        self.client_mock.ports.assert_called_once_with(**{'param': 'value'})
        self.client_mock.delete_port.assert_called_once_with(self.neutron_port)

    def test_remove_neutron_ports_list_fail(self):
        with task_manager.acquire(self.context, self.node.uuid) as task:
            self.client_mock.ports.side_effect = (
                openstack_exc.OpenStackCloudException)
            self.assertRaisesRegex(
                exception.NetworkError, 'Could not get given network VIF',
                neutron.remove_neutron_ports, task, {'param': 'value'})
        self.client_mock.ports.assert_called_once_with(**{'param': 'value'})

    def test_remove_neutron_ports_delete_fail(self):
        with task_manager.acquire(self.context, self.node.uuid) as task:
            self.client_mock.delete_port.side_effect = \
                openstack_exc.OpenStackCloudException
            self.client_mock.ports.return_value = iter([self.neutron_port])
            self.assertRaisesRegex(
                exception.NetworkError, 'Could not remove VIF',
                neutron.remove_neutron_ports, task, {'param': 'value'})
        self.client_mock.ports.assert_called_once_with(**{'param': 'value'})
        self.client_mock.delete_port.assert_called_once_with(self.neutron_port)

    def test_remove_neutron_ports_delete_race(self):
        with task_manager.acquire(self.context, self.node.uuid) as task:
            self.client_mock.delete_port.side_effect = \
                openstack_exc.ResourceNotFound
            self.client_mock.ports.return_value = iter([self.neutron_port])
            neutron.remove_neutron_ports(task, {'param': 'value'})
        self.client_mock.ports.assert_called_once_with(**{'param': 'value'})
        self.client_mock.delete_port.assert_called_once_with(self.neutron_port)

    def test__uncidr_ipv4(self):
        network, netmask = neutron._uncidr('10.0.0.0/24')
        self.assertEqual('10.0.0.0', network)
        self.assertEqual('255.255.255.0', netmask)

    def test__uncidr_ipv6(self):
        network, netmask = neutron._uncidr('::1/64', ipv6=True)
        self.assertEqual('::', network)
        self.assertEqual('ffff:ffff:ffff:ffff::', netmask)

    def test_get_neutron_port_data(self):

        network_data = neutron.get_neutron_port_data('port0', 'vif0')

        expected_port = {
            'id': 'port0',
            'type': 'vif',
            'ethernet_mac_address': 'fa:16:3e:23:fd:d7',
            'vif_id': '46d4bfb9-b26e-41f3-bd2e-e6dcc1ccedb2',
            'mtu': 1500
        }

        self.assertEqual(expected_port, network_data['links'][0])

        expected_network = {
            'id': 'a0304c3a-4f08-4c43-88af-d796509c97d2',
            'network_id': 'a87cc70a-3e15-4acf-8205-9b711a3531b7',
            'type': 'ipv4',
            'link': 'port0',
            'ip_address': '10.0.0.2',
            'netmask': '255.255.255.0',
            'routes': [
                {'gateway': '10.0.0.1',
                 'netmask': '0.0.0.0',
                 'network': '0.0.0.0'}
            ]
        }

        self.assertEqual(expected_network, network_data['networks'][0])

    def load_ipv6_files(self):
        port_show_file = os.path.join(
            os.path.dirname(__file__), 'json_samples',
            'neutron_port_show_ipv6.json')
        with open(port_show_file, 'rb') as fl:
            self.port_data = json.load(fl)

        self.client_mock.get_port.return_value = stubs.FakeNeutronPort(
            **self.port_data['port'])

        network_show_file = os.path.join(
            os.path.dirname(__file__), 'json_samples',
            'neutron_network_show_ipv6.json')
        with open(network_show_file, 'rb') as fl:
            self.network_data = json.load(fl)

        self.client_mock.get_network.return_value = stubs.FakeNeutronNetwork(
            **self.network_data['network'])

        subnet_show_file = os.path.join(
            os.path.dirname(__file__), 'json_samples',
            'neutron_subnet_show_ipv6.json')
        with open(subnet_show_file, 'rb') as fl:
            self.subnet_data = json.load(fl)

        self.client_mock.get_subnet.return_value = stubs.FakeNeutronSubnet(
            **self.subnet_data['subnet'])

    def test_get_neutron_port_data_ipv6(self):
        self.load_ipv6_files()

        network_data = neutron.get_neutron_port_data('port1', 'vif1')

        print(network_data)
        expected_port = {
            'id': 'port1',
            'type': 'vif',
            'ethernet_mac_address': '52:54:00:4f:ef:b7',
            'vif_id': '96d4bfb9-b26e-41f3-bd2e-e6dcc1ccedb8',
            'mtu': 1500
        }

        self.assertEqual(expected_port, network_data['links'][0])

        expected_network = {
            'id': '906e685a-b964-4d58-9939-9cf3af197c67',
            'network_id': 'a87cc70a-3e15-4acf-8205-9b711a3531b7',
            'type': 'ipv6',
            'link': 'port1',
            'ip_address': 'fd00:203:0:113::2',
            'netmask': 'ffff:ffff:ffff:ffff::',
            'routes': [
                {'gateway': 'fd00:203:0:113::1',
                 'netmask': '::0',
                 'network': '::0'}
            ]
        }

        self.assertEqual(expected_network, network_data['networks'][0])

    def test_get_node_portmap(self):
        with task_manager.acquire(self.context, self.node.uuid) as task:
            portmap = neutron.get_node_portmap(task)
            self.assertEqual(
                {self.ports[0].uuid: self.ports[0].local_link_connection},
                portmap
            )

    def test_get_local_group_information(self):
        pg = object_utils.create_test_portgroup(
            self.context, node_id=self.node.id,
            uuid=uuidutils.generate_uuid(),
            address='52:54:55:cf:2d:32',
            mode='802.3ad', properties={'bond_opt1': 'foo',
                                        'opt2': 'bar'},
            name='test-pg'
        )
        expected = {
            'id': pg.uuid,
            'name': pg.name,
            'bond_mode': pg.mode,
            'bond_properties': {'bond_opt1': 'foo', 'bond_opt2': 'bar'},
        }
        with task_manager.acquire(self.context, self.node.uuid) as task:
            res = neutron.get_local_group_information(task, pg)
        self.assertEqual(expected, res)

    @mock.patch.object(neutron, 'remove_ports_from_network', autospec=True)
    def test_rollback_ports(self, remove_mock):
        with task_manager.acquire(self.context, self.node.uuid) as task:
            neutron.rollback_ports(task, self.network_uuid)
            remove_mock.assert_called_once_with(task, self.network_uuid)

    @mock.patch.object(neutron, 'LOG', autospec=True)
    @mock.patch.object(neutron, 'remove_ports_from_network', autospec=True)
    def test_rollback_ports_exception(self, remove_mock, log_mock):
        remove_mock.side_effect = exception.NetworkError('boom')
        with task_manager.acquire(self.context, self.node.uuid) as task:
            neutron.rollback_ports(task, self.network_uuid)
            self.assertTrue(log_mock.exception.called)

    @mock.patch.object(neutron, 'LOG', autospec=True)
    def test_validate_port_info_neutron_interface(self, log_mock):
        self.node.network_interface = 'neutron'
        self.node.save()
        port = object_utils.create_test_port(
            self.context, node_id=self.node.id, uuid=uuidutils.generate_uuid(),
            address='52:54:00:cf:2d:33')
        res = neutron.validate_port_info(self.node, port)
        self.assertTrue(res)
        self.assertFalse(log_mock.warning.called)

    @mock.patch.object(neutron, 'LOG', autospec=True)
    def test_validate_port_info_neutron_interface_missed_info(self, log_mock):
        self.node.network_interface = 'neutron'
        self.node.save()
        llc = {}
        port = object_utils.create_test_port(
            self.context, node_id=self.node.id, uuid=uuidutils.generate_uuid(),
            address='52:54:00:cf:2d:33', local_link_connection=llc)
        res = neutron.validate_port_info(self.node, port)
        self.assertFalse(res)
        self.assertTrue(log_mock.warning.called)

    @mock.patch.object(neutron, 'LOG', autospec=True)
    def test_validate_port_info_flat_interface(self, log_mock):
        self.node.network_interface = 'flat'
        self.node.save()
        llc = {}
        port = object_utils.create_test_port(
            self.context, node_id=self.node.id, uuid=uuidutils.generate_uuid(),
            address='52:54:00:cf:2d:33', local_link_connection=llc)
        res = neutron.validate_port_info(self.node, port)
        self.assertTrue(res)
        self.assertFalse(log_mock.warning.called)

    @mock.patch.object(neutron, 'LOG', autospec=True)
    def test_validate_port_info_flat_interface_with_client_id(self, log_mock):
        self.node.network_interface = 'flat'
        self.node.save()
        llc = {}
        port = object_utils.create_test_port(
            self.context, node_id=self.node.id, uuid=uuidutils.generate_uuid(),
            address='52:54:00:cf:2d:33', local_link_connection=llc,
            extra={'client-id': self._CLIENT_ID})
        res = neutron.validate_port_info(self.node, port)
        self.assertTrue(res)
        self.assertFalse(log_mock.warning.called)

    @mock.patch.object(neutron, 'LOG', autospec=True)
    def test_validate_port_info_neutron_interface_with_client_id(
            self, log_mock):
        self.node.network_interface = 'neutron'
        self.node.save()
        llc = {}
        port = object_utils.create_test_port(
            self.context, node_id=self.node.id, uuid=uuidutils.generate_uuid(),
            address='52:54:00:cf:2d:33', local_link_connection=llc,
            extra={'client-id': self._CLIENT_ID})
        res = neutron.validate_port_info(self.node, port)
        self.assertTrue(res)
        self.assertFalse(log_mock.warning.called)

    @mock.patch.object(neutron, 'LOG', autospec=True)
    def test_validate_port_info_neutron_with_smartnic_and_link_info(
            self, log_mock):
        self.node.network_interface = 'neutron'
        self.node.save()
        llc = {'hostname': 'host1', 'port_id': 'rep0-0'}
        port = object_utils.create_test_port(
            self.context, node_id=self.node.id, uuid=uuidutils.generate_uuid(),
            address='52:54:00:cf:2d:33', local_link_connection=llc,
            is_smartnic=True)
        res = neutron.validate_port_info(self.node, port)
        self.assertTrue(res)
        self.assertFalse(log_mock.error.called)

    @mock.patch.object(neutron, 'LOG', autospec=True)
    def test_validate_port_info_neutron_with_no_smartnic_and_link_info(
            self, log_mock):
        self.node.network_interface = 'neutron'
        self.node.save()
        llc = {'hostname': 'host1', 'port_id': 'rep0-0'}
        port = object_utils.create_test_port(
            self.context, node_id=self.node.id, uuid=uuidutils.generate_uuid(),
            address='52:54:00:cf:2d:33', local_link_connection=llc,
            is_smartnic=False)
        res = neutron.validate_port_info(self.node, port)
        self.assertFalse(res)
        self.assertTrue(log_mock.error.called)

    @mock.patch.object(neutron, 'LOG', autospec=True)
    def test_validate_port_info_neutron_with_smartnic_and_no_link_info(
            self, log_mock):
        self.node.network_interface = 'neutron'
        self.node.save()
        llc = {'switch_id': 'switch', 'port_id': 'rep0-0'}
        port = object_utils.create_test_port(
            self.context, node_id=self.node.id, uuid=uuidutils.generate_uuid(),
            address='52:54:00:cf:2d:33', local_link_connection=llc,
            is_smartnic=True)
        res = neutron.validate_port_info(self.node, port)
        self.assertFalse(res)
        self.assertTrue(log_mock.error.called)

    @mock.patch.object(neutron, 'LOG', autospec=True)
    def test_validate_port_info_neutron_with_network_type_unmanaged(
            self, log_mock):
        self.node.network_interface = 'neutron'
        self.node.save()
        llc = {'network_type': 'unmanaged'}
        port = object_utils.create_test_port(
            self.context, node_id=self.node.id, uuid=uuidutils.generate_uuid(),
            address='52:54:00:cf:2d:33', local_link_connection=llc)
        res = neutron.validate_port_info(self.node, port)
        self.assertTrue(res)
        self.assertFalse(log_mock.warning.called)

    def test_validate_agent_up(self):
        self.client_mock.agents.return_value = iter([
            stubs.FakeNeutronAgent(alive=True)
        ])
        self.assertTrue(neutron._validate_agent(self.client_mock))

    def test_validate_agent_down(self):
        self.client_mock.agents.return_value = iter([
            stubs.FakeNeutronAgent(alive=False)
        ])
        self.assertFalse(neutron._validate_agent(self.client_mock))

    def test_is_smartnic_port_true(self):
        port = self.ports[0]
        port.is_smartnic = True
        self.assertTrue(neutron.is_smartnic_port(port))

    def test_is_smartnic_port_false(self):
        port = self.ports[0]
        self.assertFalse(neutron.is_smartnic_port(port))

    @mock.patch.object(neutron, '_validate_agent', autospec=True)
    @mock.patch.object(time, 'sleep', autospec=True)
    def test_wait_for_host_agent_up_target_state_up(
            self, sleep_mock, validate_agent_mock):
        validate_agent_mock.return_value = True
        self.assertTrue(neutron.wait_for_host_agent(
            self.client_mock, 'hostname'))
        sleep_mock.assert_not_called()

    @mock.patch.object(neutron, '_validate_agent', autospec=True)
    @mock.patch.object(time, 'sleep', autospec=True)
    def test_wait_for_host_agent_down_target_state_up(
            self, sleep_mock, validate_agent_mock):
        validate_agent_mock.return_value = False
        self.assertRaises(exception.NetworkError,
                          neutron.wait_for_host_agent,
                          self.client_mock, 'hostname')

    @mock.patch.object(neutron, '_validate_agent', autospec=True)
    @mock.patch.object(time, 'sleep', autospec=True)
    def test_wait_for_host_agent_up_target_state_down(
            self, sleep_mock, validate_agent_mock):
        validate_agent_mock.return_value = True
        self.assertRaises(exception.NetworkError,
                          neutron.wait_for_host_agent,
                          self.client_mock, 'hostname', target_state='down')

    @mock.patch.object(neutron, '_validate_agent', autospec=True)
    @mock.patch.object(time, 'sleep', autospec=True)
    def test_wait_for_host_agent_down_target_state_down(
            self, sleep_mock, validate_agent_mock):
        validate_agent_mock.return_value = False
        self.assertTrue(
            neutron.wait_for_host_agent(self.client_mock, 'hostname',
                                        target_state='down'))
        sleep_mock.assert_not_called()

    @mock.patch.object(neutron, '_get_port_by_uuid', autospec=True)
    @mock.patch.object(time, 'sleep', autospec=True)
    def test_wait_for_port_status_up(self, sleep_mock, get_port_mock):
        get_port_mock.return_value = stubs.FakeNeutronPort(status='ACTIVE')
        neutron.wait_for_port_status(self.client_mock, 'port_id', 'ACTIVE')
        sleep_mock.assert_not_called()

    @mock.patch.object(neutron, '_get_port_by_uuid', autospec=True)
    @mock.patch.object(time, 'sleep', autospec=True)
    def test_wait_for_port_status_down(self, sleep_mock, get_port_mock):
        get_port_mock.side_effect = [stubs.FakeNeutronPort(status='DOWN'),
                                     stubs.FakeNeutronPort(status='ACTIVE')]
        neutron.wait_for_port_status(self.client_mock, 'port_id', 'ACTIVE')
        sleep_mock.assert_called_once()

    @mock.patch.object(neutron, '_get_port_by_uuid', autospec=True)
    @mock.patch.object(time, 'sleep', autospec=True)
    def test_wait_for_port_status_active_max_retry(self, sleep_mock,
                                                   get_port_mock):
        get_port_mock.return_value = stubs.FakeNeutronPort(status='DOWN')
        self.assertRaises(exception.NetworkError,
                          neutron.wait_for_port_status,
                          self.client_mock, 'port_id', 'ACTIVE')

    @mock.patch.object(neutron, '_get_port_by_uuid', autospec=True)
    @mock.patch.object(time, 'sleep', autospec=True)
    def test_wait_for_port_status_down_max_retry(self, sleep_mock,
                                                 get_port_mock):
        get_port_mock.return_value = stubs.FakeNeutronPort(status='ACTIVE')
        self.assertRaises(exception.NetworkError,
                          neutron.wait_for_port_status,
                          self.client_mock, 'port_id', 'DOWN')

    @mock.patch.object(neutron, 'update_neutron_port', autospec=True)
    @mock.patch.object(neutron, 'wait_for_host_agent', autospec=True)
    @mock.patch.object(neutron, 'wait_for_port_status', autospec=True)
    def test_add_smartnic_port_to_network(
            self, wait_port_mock, wait_agent_mock, update_mock):
        # Ports will be created only if pxe_enabled is True
        self.node.network_interface = 'neutron'
        self.node.save()
        object_utils.create_test_port(
            self.context, node_id=self.node.id,
            uuid=uuidutils.generate_uuid(),
            address='52:54:00:cf:2d:22',
            pxe_enabled=False
        )
        port = self.ports[0]

        local_link_connection = port.local_link_connection
        local_link_connection['hostname'] = 'hostname'
        port.local_link_connection = local_link_connection
        port.is_smartnic = True
        port.save()

        expected_create_attrs = {
            'network_id': self.network_uuid,
            'admin_state_up': True,
            'binding:vnic_type': 'smart-nic',
            'device_id': self.node.uuid,
        }
        expected_update_attrs = {
            'device_owner': 'baremetal:none',
            'binding:host_id': port.local_link_connection['hostname'],
            'mac_address': port.address,
            'binding:profile': {
                'local_link_information': [port.local_link_connection]
            },
        }

        # Ensure we can create ports
        self.client_mock.create_port.return_value = self.neutron_port
        update_mock.return_value = self.neutron_port
        expected = {port.uuid: self.neutron_port.id}
        with task_manager.acquire(self.context, self.node.uuid) as task:
            ports = neutron.add_ports_to_network(task, self.network_uuid)
            self.assertEqual(expected, ports)
            self.client_mock.create_port.assert_called_once_with(
                **expected_create_attrs)
            update_mock.assert_called_once_with(
                self.context, self.neutron_port.id, expected_update_attrs)
            wait_agent_mock.assert_called_once_with(
                self.client_mock, 'hostname')
            wait_port_mock.assert_called_once_with(
                self.client_mock, self.neutron_port.id, 'ACTIVE')

    @mock.patch.object(neutron, 'is_smartnic_port', autospec=True)
    @mock.patch.object(neutron, 'wait_for_host_agent', autospec=True)
    def test_remove_neutron_smartnic_ports(
            self, wait_agent_mock, is_smartnic_mock):
        with task_manager.acquire(self.context, self.node.uuid) as task:
            is_smartnic_mock.return_value = True
            self.neutron_port['binding:host_id'] = 'hostname'
            self.client_mock.ports.return_value = iter([self.neutron_port])
            neutron.remove_neutron_ports(task, {'param': 'value'})
        self.client_mock.ports.assert_called_once_with(
            **{'param': 'value'})
        self.client_mock.delete_port.assert_called_once_with(
            self.neutron_port)
        is_smartnic_mock.assert_called_once_with(self.neutron_port)
        wait_agent_mock.assert_called_once_with(self.client_mock, 'hostname')


@mock.patch.object(neutron, 'get_client', autospec=True)
class TestValidateNetwork(base.TestCase):
    def setUp(self):
        super(TestValidateNetwork, self).setUp()

        self.uuid = uuidutils.generate_uuid()
        self.context = context.RequestContext()

    def test_by_uuid(self, client_mock):
        net_mock = client_mock.return_value.find_network
        net_mock.return_value = stubs.FakeNeutronNetwork(id=self.uuid)

        self.assertEqual(self.uuid, neutron.validate_network(
            self.uuid, context=self.context))
        net_mock.assert_called_once_with(self.uuid, ignore_missing=False)

    def test_by_name(self, client_mock):
        net_mock = client_mock.return_value.find_network
        net_mock.return_value = stubs.FakeNeutronNetwork(id=self.uuid,
                                                         name='name')

        self.assertEqual(self.uuid, neutron.validate_network(
            'name', context=self.context))
        net_mock.assert_called_once_with('name', ignore_missing=False)

    def test_not_found(self, client_mock):
        net_mock = client_mock.return_value.find_network
        net_mock.side_effect = openstack_exc.ResourceNotFound()

        self.assertRaisesRegex(exception.InvalidParameterValue,
                               'was not found',
                               neutron.validate_network,
                               self.uuid, context=self.context)
        net_mock.assert_called_once_with(self.uuid, ignore_missing=False)

    def test_failure(self, client_mock):
        net_mock = client_mock.return_value.find_network
        net_mock.side_effect = openstack_exc.OpenStackCloudException('foo')

        self.assertRaisesRegex(exception.NetworkError, 'foo',
                               neutron.validate_network, 'name',
                               context=self.context)
        net_mock.assert_called_once_with('name', ignore_missing=False)

    def test_duplicate(self, client_mock):
        net_mock = client_mock.return_value.find_network
        net_mock.side_effect = openstack_exc.DuplicateResource()

        self.assertRaisesRegex(exception.InvalidParameterValue,
                               'More than one network',
                               neutron.validate_network, 'name',
                               context=self.context)
        net_mock.assert_called_once_with('name', ignore_missing=False)


@mock.patch.object(neutron, 'get_client', autospec=True)
class TestUpdatePortAddress(base.TestCase):

    def setUp(self):
        super(TestUpdatePortAddress, self).setUp()
        self.context = context.RequestContext()

    @mock.patch.object(neutron, 'update_neutron_port', autospec=True)
    def test_update_port_address(self, mock_unp, mock_client):
        address = 'fe:54:00:77:07:d9'
        port_id = 'fake-port-id'
        expected = {'mac_address': address}
        mock_client.return_value.get_port.return_value = {}

        neutron.update_port_address(port_id, address, context=self.context)
        mock_unp.assert_called_once_with(self.context, port_id, expected)

    @mock.patch.object(neutron, 'update_neutron_port', autospec=True)
    @mock.patch.object(neutron, 'unbind_neutron_port', autospec=True)
    def test_update_port_address_with_binding(self, mock_unp, mock_update,
                                              mock_client):
        address = 'fe:54:00:77:07:d9'
        port_id = 'fake-port-id'

        mock_client.return_value.get_port.return_value = {
            'binding:host_id': 'host', 'binding:profile': 'foo'}

        calls = [mock.call(self.context, port_id, {'mac_address': address}),
                 mock.call(self.context, port_id, {'binding:host_id': 'host',
                                                   'binding:profile': 'foo'})]

        neutron.update_port_address(port_id, address, context=self.context)
        mock_unp.assert_called_once_with(
            port_id,
            context=self.context)
        mock_update.assert_has_calls(calls)

    @mock.patch.object(neutron, 'update_neutron_port', autospec=True)
    @mock.patch.object(neutron, 'unbind_neutron_port', autospec=True)
    def test_update_port_address_without_binding(self, mock_unp, mock_update,
                                                 mock_client):
        address = 'fe:54:00:77:07:d9'
        port_id = 'fake-port-id'
        expected = {'mac_address': address}
        mock_client.return_value.get_port.return_value = {
            'binding:profile': 'foo'}

        neutron.update_port_address(port_id, address, context=self.context)
        self.assertFalse(mock_unp.called)
        mock_update.assert_any_call(self.context, port_id, expected)

    def test_update_port_address_show_failed(self, mock_client):
        address = 'fe:54:00:77:07:d9'
        port_id = 'fake-port-id'
        mock_client.return_value.get_port.side_effect = (
            openstack_exc.OpenStackCloudException())

        self.assertRaises(exception.FailedToUpdateMacOnPort,
                          neutron.update_port_address,
                          port_id, address, context=self.context)
        self.assertFalse(mock_client.return_value.update_port.called)

    @mock.patch.object(neutron, 'unbind_neutron_port', autospec=True)
    def test_update_port_address_unbind_port_failed(self, mock_unp,
                                                    mock_client):
        address = 'fe:54:00:77:07:d9'
        port_id = 'fake-port-id'
        mock_client.return_value.get_port.return_value = {
            'binding:profile': 'foo', 'binding:host_id': 'host'}
        mock_unp.side_effect = (exception.NetworkError('boom'))
        self.assertRaises(exception.FailedToUpdateMacOnPort,
                          neutron.update_port_address,
                          port_id, address, context=self.context)
        mock_unp.assert_called_once_with(
            port_id,
            context=self.context)
        self.assertFalse(mock_client.return_value.update_port.called)

    @mock.patch.object(neutron, 'update_neutron_port', autospec=True)
    @mock.patch.object(neutron, 'unbind_neutron_port', autospec=True)
    def test_update_port_address_with_exception(self, mock_unp,
                                                mock_update,
                                                mock_client):
        address = 'fe:54:00:77:07:d9'
        port_id = 'fake-port-id'
        mock_client.return_value.get_port.return_value = {}
        mock_update.side_effect = (
            openstack_exc.OpenStackCloudException())

        self.assertRaises(exception.FailedToUpdateMacOnPort,
                          neutron.update_port_address,
                          port_id, address, context=self.context)


@mock.patch.object(neutron, 'update_neutron_port', autospec=True)
class TestUnbindPort(base.TestCase):

    def setUp(self):
        super(TestUnbindPort, self).setUp()
        self.context = context.RequestContext()

    def test_unbind_neutron_port_client_passed(self, mock_unp):
        port_id = 'fake-port-id'
        attr_unbind = {'binding:host_id': '', 'binding:profile': {}}
        attr_reset_mac = {'mac_address': None}
        client = mock.MagicMock()
        update_calls = [
            mock.call(self.context, port_id, attr_unbind, client),
            mock.call(self.context, port_id, attr_reset_mac, client)
        ]
        neutron.unbind_neutron_port(port_id, client, context=self.context)
        self.assertEqual(2, mock_unp.call_count)
        mock_unp.assert_has_calls(update_calls)

    @mock.patch.object(neutron, 'LOG', autospec=True)
    def test_unbind_neutron_port_failure(self, mock_log, mock_unp):
        mock_unp.side_effect = openstack_exc.OpenStackCloudException()
        attr = {'binding:host_id': '', 'binding:profile': {}}
        port_id = 'fake-port-id'
        self.assertRaises(exception.NetworkError, neutron.unbind_neutron_port,
                          port_id, context=self.context)
        mock_unp.assert_called_once_with(self.context, port_id, attr, None)
        mock_log.exception.assert_called_once()

    def test_unbind_neutron_port(self, mock_unp):
        port_id = 'fake-port-id'
        attr_unbind = {'binding:host_id': '', 'binding:profile': {}}
        attr_reset_mac = {'mac_address': None}
        update_calls = [
            mock.call(self.context, port_id, attr_unbind, None),
            mock.call(self.context, port_id, attr_reset_mac, None)
        ]
        neutron.unbind_neutron_port(port_id, context=self.context)
        mock_unp.assert_has_calls(update_calls)

    def test_unbind_neutron_port_not_reset_mac(self, mock_unp):
        port_id = 'fake-port-id'
        attr_unbind = {'binding:host_id': '', 'binding:profile': {}}
        neutron.unbind_neutron_port(port_id, context=self.context,
                                    reset_mac=False)
        mock_unp.assert_called_once_with(self.context, port_id, attr_unbind,
                                         None)

    @mock.patch.object(neutron, 'LOG', autospec=True)
    def test_unbind_neutron_port_not_found(self, mock_log, mock_unp):
        port_id = 'fake-port-id'
        mock_unp.side_effect = (
            openstack_exc.ResourceNotFound())
        attr = {'binding:host_id': '', 'binding:profile': {}}
        neutron.unbind_neutron_port(port_id, context=self.context)
        mock_unp.assert_called_once_with(self.context, port_id, attr, None)
        mock_log.info.assert_called_once_with('Port %s was not found while '
                                              'unbinding.', port_id)


class TestGetNetworkByUUIDOrName(base.TestCase):

    def setUp(self):
        super(TestGetNetworkByUUIDOrName, self).setUp()
        self.client = mock.MagicMock()

    def test__get_network_by_uuid_or_name_uuid(self):
        network_uuid = '9acb0256-2c1b-420a-b9d7-62bee90b6ed7'
        network = stubs.FakeNeutronNetwork(id=network_uuid)
        self.client.find_network.return_value = network
        result = neutron._get_network_by_uuid_or_name(
            self.client, network_uuid)
        self.client.find_network.assert_called_once_with(
            network_uuid, ignore_missing=False)
        self.assertEqual(network, result)

    def test__get_network_by_uuid_or_name_name(self):
        network_name = 'test-net'
        network = stubs.FakeNeutronNetwork(name=network_name)
        self.client.find_network.return_value = network
        result = neutron._get_network_by_uuid_or_name(
            self.client, network_name)
        self.client.find_network.assert_called_once_with(
            network_name, ignore_missing=False)
        self.assertEqual(network, result)

    def test__get_network_by_uuid_or_name_failure(self):
        network_uuid = '9acb0256-2c1b-420a-b9d7-62bee90b6ed7'
        self.client.find_network.side_effect = (
            openstack_exc.OpenStackCloudException())
        self.assertRaises(exception.NetworkError,
                          neutron._get_network_by_uuid_or_name,
                          self.client, network_uuid)
        self.client.find_network.assert_called_once_with(
            network_uuid, ignore_missing=False)

    def test__get_network_by_uuid_or_name_missing(self):
        network_uuid = '9acb0256-2c1b-420a-b9d7-62bee90b6ed7'
        self.client.find_network.side_effect = (
            openstack_exc.ResourceNotFound())
        self.assertRaises(exception.InvalidParameterValue,
                          neutron._get_network_by_uuid_or_name,
                          self.client, network_uuid)
        self.client.find_network.assert_called_once_with(
            network_uuid, ignore_missing=False)

    def test__get_network_by_uuid_or_name_duplicate(self):
        network_name = 'test-net'
        self.client.find_network.side_effect = (
            openstack_exc.DuplicateResource())
        self.assertRaises(exception.InvalidParameterValue,
                          neutron._get_network_by_uuid_or_name,
                          self.client, network_name)
        self.client.find_network.assert_called_once_with(
            network_name, ignore_missing=False)


@mock.patch.object(neutron, '_get_network_by_uuid_or_name', autospec=True)
@mock.patch.object(neutron, '_get_port_by_uuid', autospec=True)
class TestGetPhysnetsByPortUUID(base.TestCase):

    PORT_FIELDS = ['network_id']
    NETWORK_FIELDS = ['provider:physical_network', 'segments']

    def setUp(self):
        super(TestGetPhysnetsByPortUUID, self).setUp()
        self.client = mock.MagicMock()

    def test_get_physnets_by_port_uuid_single_segment(self, mock_gp, mock_gn):
        port_uuid = 'fake-port-uuid'
        network_uuid = 'fake-network-uuid'
        physnet = 'fake-physnet'
        mock_gp.return_value = stubs.FakeNeutronPort(network_id=network_uuid)
        mock_gn.return_value = stubs.FakeNeutronNetwork(
            **{'segments': [
                {'provider:physical_network': physnet}
            ]})
        result = neutron.get_physnets_by_port_uuid(self.client, port_uuid)
        mock_gp.assert_called_once_with(self.client, port_uuid)
        mock_gn.assert_called_once_with(self.client, network_uuid)
        self.assertEqual({physnet}, result)

    def test_get_physnets_by_port_uuid_no_segment_no_physnet(
            self, mock_gp, mock_gn):
        port_uuid = 'fake-port-uuid'
        network_uuid = 'fake-network-uuid'
        mock_gp.return_value = stubs.FakeNeutronPort(network_id=network_uuid)
        fake_network = stubs.FakeNeutronNetwork(
            **{'provider:physical_network': None})
        mock_gn.return_value = fake_network
        result = neutron.get_physnets_by_port_uuid(self.client, port_uuid)
        mock_gp.assert_called_once_with(self.client, port_uuid)
        mock_gn.assert_called_once_with(self.client, network_uuid)
        self.assertEqual(set(), result)

    def test_get_physnets_by_port_uuid_no_segment(
            self, mock_gp, mock_gn):
        port_uuid = 'fake-port-uuid'
        network_uuid = 'fake-network-uuid'
        physnet = 'fake-physnet'
        mock_gp.return_value = stubs.FakeNeutronPort(network_id=network_uuid)
        fake_network = stubs.FakeNeutronNetwork(
            **{'provider:physical_network': physnet})
        mock_gn.return_value = fake_network
        result = neutron.get_physnets_by_port_uuid(self.client, port_uuid)
        mock_gp.assert_called_once_with(self.client, port_uuid)
        mock_gn.assert_called_once_with(self.client, network_uuid)
        self.assertEqual({physnet}, result)

    def test_get_physnets_by_port_uuid_multiple_segments(self, mock_gp,
                                                         mock_gn):
        port_uuid = 'fake-port-uuid'
        network_uuid = 'fake-network-uuid'
        physnet1 = 'fake-physnet-1'
        physnet2 = 'fake-physnet-2'
        mock_gp.return_value = stubs.FakeNeutronPort(network_id=network_uuid)
        mock_gn.return_value = stubs.FakeNeutronNetwork(
            **{'segments': [{'provider:physical_network': physnet1},
                            {'provider:physical_network': physnet2}]})
        result = neutron.get_physnets_by_port_uuid(self.client, port_uuid)
        mock_gp.assert_called_once_with(self.client, port_uuid)
        mock_gn.assert_called_once_with(self.client, network_uuid)
        self.assertEqual({physnet1, physnet2}, result)

    def test_get_physnets_by_port_uuid_multiple_segments_no_physnet(
            self, mock_gp, mock_gn):
        port_uuid = 'fake-port-uuid'
        network_uuid = 'fake-network-uuid'
        mock_gp.return_value = stubs.FakeNeutronPort(network_id=network_uuid)
        mock_gn.return_value = stubs.FakeNeutronNetwork(
            **{'segments': [{'provider:physical_network': None},
                            {'provider:physical_network': None}]})
        result = neutron.get_physnets_by_port_uuid(self.client, port_uuid)
        mock_gp.assert_called_once_with(self.client, port_uuid)
        mock_gn.assert_called_once_with(self.client, network_uuid)
        self.assertEqual(set(), result)

    def test_get_physnets_by_port_uuid_port_missing(self, mock_gp, mock_gn):
        port_uuid = 'fake-port-uuid'
        mock_gp.side_effect = exception.InvalidParameterValue('error')
        self.assertRaises(exception.InvalidParameterValue,
                          neutron.get_physnets_by_port_uuid,
                          self.client, port_uuid)
        mock_gp.assert_called_once_with(self.client, port_uuid)
        self.assertFalse(mock_gn.called)

    def test_get_physnets_by_port_uuid_port_failure(self, mock_gp, mock_gn):
        port_uuid = 'fake-port-uuid'
        mock_gp.side_effect = exception.NetworkError
        self.assertRaises(exception.NetworkError,
                          neutron.get_physnets_by_port_uuid,
                          self.client, port_uuid)
        mock_gp.assert_called_once_with(self.client, port_uuid)
        self.assertFalse(mock_gn.called)

    def test_get_physnets_by_port_uuid_network_missing(
            self, mock_gp, mock_gn):
        port_uuid = 'fake-port-uuid'
        network_uuid = 'fake-network-uuid'
        mock_gp.return_value = stubs.FakeNeutronPort(network_id=network_uuid)
        mock_gn.side_effect = exception.InvalidParameterValue('error')
        self.assertRaises(exception.InvalidParameterValue,
                          neutron.get_physnets_by_port_uuid,
                          self.client, port_uuid)
        mock_gp.assert_called_once_with(self.client, port_uuid)
        mock_gn.assert_called_once_with(self.client, network_uuid)

    def test_get_physnets_by_port_uuid_network_failure(
            self, mock_gp, mock_gn):
        port_uuid = 'fake-port-uuid'
        network_uuid = 'fake-network-uuid'
        mock_gp.return_value = stubs.FakeNeutronPort(network_id=network_uuid)
        mock_gn.side_effect = exception.NetworkError
        self.assertRaises(exception.NetworkError,
                          neutron.get_physnets_by_port_uuid,
                          self.client, port_uuid)
        mock_gp.assert_called_once_with(self.client, port_uuid)
        mock_gn.assert_called_once_with(self.client, network_uuid)
