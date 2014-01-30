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

from neutronclient.v2_0 import client
from oslo.config import cfg

from ironic.common import exception
from ironic.common import neutron
from ironic.openstack.common import context
from ironic.tests import base

CONF = cfg.CONF


class TestNeutron(base.TestCase):

    def setUp(self):
        super(TestNeutron, self).setUp()
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
            neutron.NeutronAPI(my_context)
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
            neutron.NeutronAPI(my_context)
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
            api = neutron.NeutronAPI(my_context)
            with mock.patch.object(client.Client,
                                   "update_port") as mock_update_port:
                mock_update_port.return_value = None
                api.update_port_dhcp_opts(port_id, opts)
                mock_update_port.assert_called_once_with(port_id, expected)

    def test_neutron_port_update_with_execption(self):
        opts = [{}]
        port_id = 'fake-port-id'
        my_context = context.RequestContext(user='test-user',
                                            tenant='test-tenant')
        with mock.patch.object(client.Client, "__init__") as mock_client_init:
            mock_client_init.return_value = None
            api = neutron.NeutronAPI(my_context)
            with mock.patch.object(client.Client,
                                   "update_port") as mock_update_port:
                mock_update_port.side_effect = (
                    exception.FailedToUpdateDHCPOptOnPort("test exception"))
                self.assertRaises(
                        exception.FailedToUpdateDHCPOptOnPort,
                        api.update_port_dhcp_opts,
                        port_id, opts)
