#
# Copyright 2014 OpenStack Foundation
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

import mock
from neutronclient.common import exceptions as neutron_client_exc
from neutronclient.v2_0 import client

from ironic.common import dhcp_factory
from ironic.common import exception
from ironic.common import pxe_utils
from ironic.common import utils
from ironic.conductor import task_manager
from ironic.dhcp import neutron
from ironic.openstack.common import context
from ironic.tests import base
from ironic.tests.conductor import utils as mgr_utils
from ironic.tests.objects import utils as object_utils


class TestNeutron(base.TestCase):

    def setUp(self):
        super(TestNeutron, self).setUp()
        mgr_utils.mock_the_extension_manager(driver='fake')
        self.config(enabled_drivers=['fake'])
        self.config(dhcp_provider='neutron',
                    group='dhcp')
        self.config(url='test-url',
                    url_timeout=30,
                    group='neutron')
        self.config(insecure=False,
                    certfile='test-file',
                    admin_user='test-admin-user',
                    admin_tenant_name='test-admin-tenant',
                    admin_password='test-admin-password',
                    auth_uri='test-auth-uri',
                    group='keystone_authtoken')
        self.context = context.get_admin_context()
        self.node = object_utils.create_test_node(self.context)
        dhcp_factory.DHCPFactory._dhcp_provider = None

    def test_invalid_auth_strategy(self):
        self.config(auth_strategy='wrong_config', group='neutron')
        token = 'test-token-123'
        self.assertRaises(exception.ConfigInvalid,
                          neutron.NeutronDHCPApi,
                          token=token)

    def test_create_with_token(self):
        token = 'test-token-123'
        my_context = context.RequestContext(user='test-user',
                                            tenant='test-tenant',
                                            auth_token=token)
        expected = {'timeout': 30,
                    'insecure': False,
                    'ca_cert': 'test-file',
                    'token': token,
                    'endpoint_url': 'test-url',
                    'auth_strategy': None}

        with mock.patch.object(client.Client, "__init__") as mock_client_init:
            mock_client_init.return_value = None
            neutron.NeutronDHCPApi(token=my_context.auth_token)
            mock_client_init.assert_called_once_with(**expected)

    def test_create_without_token(self):
        my_context = context.RequestContext(user='test-user',
                                            tenant='test-tenant')
        expected = {'timeout': 30,
                    'insecure': False,
                    'ca_cert': 'test-file',
                    'endpoint_url': 'test-url',
                    'username': 'test-admin-user',
                    'tenant_name': 'test-admin-tenant',
                    'password': 'test-admin-password',
                    'auth_url': 'test-auth-uri'}

        with mock.patch.object(client.Client, "__init__") as mock_client_init:
            mock_client_init.return_value = None
            neutron.NeutronDHCPApi(token=my_context.auth_token)
            mock_client_init.assert_called_once_with(**expected)

    def test_create_noauth(self):
        self.config(auth_strategy='noauth', group='neutron')
        my_context = context.RequestContext()
        expected = {'ca_cert': 'test-file',
                    'insecure': False,
                    'endpoint_url': 'test-url',
                    'timeout': 30,
                    'auth_strategy': 'noauth'}

        with mock.patch.object(client.Client, "__init__") as mock_client_init:
            mock_client_init.return_value = None
            neutron.NeutronDHCPApi(token=my_context.auth_token)
            mock_client_init.assert_called_once_with(**expected)

    def test_neutron_port_update(self):
        opts = [{'opt_name': 'bootfile-name',
                 'opt_value': 'pxelinux.0'},
                {'opt_name': 'tftp-server',
                 'opt_value': '1.1.1.1'},
                {'opt_name': 'server-ip-address',
                 'opt_value': '1.1.1.1'}]
        port_id = 'fake-port-id'
        expected = {'port': {'extra_dhcp_opts': opts}}
        my_context = context.RequestContext(user='test-user',
                                            tenant='test-tenant')

        with mock.patch.object(client.Client, "__init__") as mock_client_init:
            mock_client_init.return_value = None
            api = dhcp_factory.DHCPFactory(token=my_context.auth_token)
            with mock.patch.object(client.Client,
                                   "update_port") as mock_update_port:
                mock_update_port.return_value = None
                api = dhcp_factory.DHCPFactory(token=my_context.auth_token)
                api.provider.update_port_dhcp_opts(port_id, opts)
                mock_update_port.assert_called_once_with(port_id, expected)

    def test_neutron_port_update_with_execption(self):
        opts = [{}]
        port_id = 'fake-port-id'
        my_context = context.RequestContext(user='test-user',
                                            tenant='test-tenant')
        with mock.patch.object(client.Client, "__init__") as mock_client_init:
            mock_client_init.return_value = None
            api = dhcp_factory.DHCPFactory(token=my_context.auth_token)
            with mock.patch.object(client.Client,
                                   "update_port") as mock_update_port:
                mock_update_port.side_effect = (
                    neutron_client_exc.NeutronClientException())
                api = dhcp_factory.DHCPFactory(token=my_context.auth_token)
                self.assertRaises(
                        exception.FailedToUpdateDHCPOptOnPort,
                        api.provider.update_port_dhcp_opts,
                        port_id, opts)

    @mock.patch.object(client.Client, 'update_port')
    @mock.patch.object(client.Client, '__init__')
    def test_neutron_address_update(self, mock_client_init, mock_update_port):
        address = 'fe:54:00:77:07:d9'
        port_id = 'fake-port-id'
        expected = {'port': {'mac_address': address}}
        my_context = context.RequestContext(user='test-user',
                                            tenant='test-tenant')
        mock_client_init.return_value = None
        api = dhcp_factory.DHCPFactory(token=my_context.auth_token)
        mock_update_port.return_value = None
        api.provider.update_port_address(port_id, address)
        mock_update_port.assert_called_once_with(port_id, expected)

    @mock.patch.object(client.Client, 'update_port')
    @mock.patch.object(client.Client, '__init__')
    def test_neutron_address_update_with_exception(self, mock_client_init,
                                                   mock_update_port):
        address = 'fe:54:00:77:07:d9'
        port_id = 'fake-port-id'
        my_context = context.RequestContext(user='test-user',
                                            tenant='test-tenant')
        mock_client_init.return_value = None
        api = dhcp_factory.DHCPFactory(token=my_context.auth_token)
        mock_update_port.side_effect = (
            neutron_client_exc.NeutronClientException())
        self.assertRaises(exception.FailedToUpdateMacOnPort,
                          api.provider.update_port_address,
                          port_id, address)

    @mock.patch('ironic.dhcp.neutron.NeutronDHCPApi.update_port_dhcp_opts')
    @mock.patch('ironic.common.network.get_node_vif_ids')
    def test_update_dhcp(self, mock_gnvi, mock_updo):
        mock_gnvi.return_value = {'port-uuid': 'vif-uuid'}
        with task_manager.acquire(self.context,
                                  self.node.uuid) as task:
            opts = pxe_utils.dhcp_options_for_instance(task)
            api = dhcp_factory.DHCPFactory(token=self.context.auth_token)
            api.update_dhcp(task, self.node)
        mock_updo.assertCalleOnceWith('vif-uuid', opts)

    @mock.patch('ironic.common.network.get_node_vif_ids')
    def test_update_dhcp_no_vif_data(self, mock_gnvi):
        mock_gnvi.return_value = {}
        with task_manager.acquire(self.context,
                                  self.node.uuid) as task:
            api = dhcp_factory.DHCPFactory(token=self.context.auth_token)
            api.update_dhcp(task, self.node)

    @mock.patch('ironic.dhcp.neutron.NeutronDHCPApi.update_port_dhcp_opts')
    @mock.patch('ironic.common.network.get_node_vif_ids')
    def test_update_dhcp_some_failures(self, mock_gnvi, mock_updo):
        # confirm update is called twice, one fails, but no exception raised
        mock_gnvi.return_value = {'p1': 'v1', 'p2': 'v2'}
        exc = exception.FailedToUpdateDHCPOptOnPort('fake exception')
        mock_updo.side_effect = [None, exc]
        with task_manager.acquire(self.context,
                                  self.node.uuid) as task:
            api = dhcp_factory.DHCPFactory(token=self.context.auth_token)
            api.update_dhcp(task, self.node)
            mock_gnvi.assertCalleOnceWith(task)
        self.assertEqual(2, mock_updo.call_count)

    @mock.patch('ironic.dhcp.neutron.NeutronDHCPApi.update_port_dhcp_opts')
    @mock.patch('ironic.common.network.get_node_vif_ids')
    def test_update_dhcp_fails(self, mock_gnvi, mock_updo):
        # confirm update is called twice, both fail, and exception is raised
        mock_gnvi.return_value = {'p1': 'v1', 'p2': 'v2'}
        exc = exception.FailedToUpdateDHCPOptOnPort('fake exception')
        mock_updo.side_effect = [exc, exc]
        with task_manager.acquire(self.context,
                                  self.node.uuid) as task:
            api = dhcp_factory.DHCPFactory(token=self.context.auth_token)
            self.assertRaises(exception.FailedToUpdateDHCPOptOnPort,
                              api.update_dhcp,
                              task, self.node)
            mock_gnvi.assertCalleOnceWith(task)
        self.assertEqual(2, mock_updo.call_count)

    @mock.patch.object(client.Client, 'show_port')
    @mock.patch.object(client.Client, '__init__')
    def test_neutron__get_fixed_ip_address(self, mock_client_init,
                                          mock_show_port):
        port_id = 'fake-port-id'
        expected = "192.168.1.3"
        mock_client_init.return_value = None
        api = dhcp_factory.DHCPFactory().provider
        port_data = {
            "id": port_id,
            "network_id": "3cb9bc59-5699-4588-a4b1-b87f96708bc6",
            "admin_state_up": True,
            "status": "ACTIVE",
            "mac_address": "fa:16:3e:4c:2c:30",
            "fixed_ips": [
                {
                    "ip_address": "192.168.1.3",
                    "subnet_id": "f8a6e8f8-c2ec-497c-9f23-da9616de54ef"
                }
            ],
            "device_id": 'bece68a3-2f8b-4e66-9092-244493d6aba7',
            }
        port = {'port': port_data}
        mock_show_port.return_value = port
        result = api._get_fixed_ip_address(port_id)
        self.assertEqual(expected, result)

    @mock.patch.object(client.Client, 'show_port')
    @mock.patch.object(client.Client, '__init__')
    def test_neutron__get_fixed_ip_address_invalid_ip(self, mock_client_init,
                                                      mock_show_port):
        port_id = 'fake-port-id'
        mock_client_init.return_value = None
        api = dhcp_factory.DHCPFactory().provider
        port_data = {
            "id": port_id,
            "network_id": "3cb9bc59-5699-4588-a4b1-b87f96708bc6",
            "admin_state_up": True,
            "status": "ACTIVE",
            "mac_address": "fa:16:3e:4c:2c:30",
            "fixed_ips": [
                {
                    "ip_address": "invalid.ip",
                    "subnet_id": "f8a6e8f8-c2ec-497c-9f23-da9616de54ef"
                }
            ],
            "device_id": 'bece68a3-2f8b-4e66-9092-244493d6aba7',
            }
        port = {'port': port_data}
        mock_show_port.return_value = port
        self.assertRaises(exception.InvalidIPv4Address,
                          api._get_fixed_ip_address,
                          port_id)
        mock_show_port.assert_called_once_with(port_id)

    @mock.patch.object(client.Client, 'show_port')
    @mock.patch.object(client.Client, '__init__')
    def test_neutron__get_fixed_ip_address_with_exception(self,
                                    mock_client_init, mock_show_port):
        port_id = 'fake-port-id'
        mock_client_init.return_value = None
        api = dhcp_factory.DHCPFactory().provider

        mock_show_port.side_effect = (
                                neutron_client_exc.NeutronClientException())
        self.assertRaises(exception.FailedToGetIPAddressOnPort,
                          api._get_fixed_ip_address, port_id)
        mock_show_port.assert_called_once_with(port_id)

    @mock.patch('ironic.dhcp.neutron.NeutronDHCPApi._get_fixed_ip_address')
    @mock.patch('ironic.common.network.get_node_vif_ids')
    def test__get_port_ip_address(self, mock_gnvi, mock_gfia):
        expected = "192.168.1.3"
        port = object_utils.create_test_port(self.context,
                                           node_id=self.node.id,
                                           id=6, address='aa:bb:cc',
                                           uuid=utils.generate_uuid(),
                                           extra={'vif_port_id': 'test-vif-A'},
                                           driver='fake')
        mock_gnvi.return_value = {port.uuid: 'vif-uuid'}
        mock_gfia.return_value = expected
        with task_manager.acquire(self.context,
                                  self.node.uuid) as task:
            api = dhcp_factory.DHCPFactory(token=task.context.auth_token)
            api = api.provider
            result = api._get_port_ip_address(task, port.uuid)
        self.assertEqual(expected, result)

    @mock.patch('ironic.dhcp.neutron.NeutronDHCPApi._get_fixed_ip_address')
    @mock.patch('ironic.common.network.get_node_vif_ids')
    def test__get_port_ip_address_with_exception(self, mock_gnvi, mock_gfia):
        expected = "192.168.1.3"
        port = object_utils.create_test_port(self.context,
                                           node_id=self.node.id,
                                           id=6, address='aa:bb:cc',
                                           uuid=utils.generate_uuid(),
                                           extra={'vif_port_id': 'test-vif-A'},
                                           driver='fake')
        mock_gnvi.return_value = None
        mock_gfia.return_value = expected
        with task_manager.acquire(self.context,
                                  self.node.uuid) as task:
            api = dhcp_factory.DHCPFactory().provider
            self.assertRaises(exception.FailedToGetIPAddressOnPort,
                              api._get_port_ip_address, task, port)

    @mock.patch('ironic.dhcp.neutron.NeutronDHCPApi._get_port_ip_address')
    def test_get_ip_addresses(self, get_ip_mock):
        ip_address = '10.10.0.1'
        address = "aa:aa:aa:aa:aa:aa"
        expected = [ip_address]
        object_utils.create_test_port(self.context, node_uuid=self.node.uuid,
                                      address=address)

        get_ip_mock.return_value = ip_address

        with task_manager.acquire(self.context, self.node.uuid) as task:
            api = dhcp_factory.DHCPFactory().provider
            result = api.get_ip_addresses(task)
        self.assertEqual(expected, result)
