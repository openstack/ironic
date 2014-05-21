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
from oslo.config import cfg

from ironic.common import exception
from ironic.common import neutron
from ironic.common import tftp
from ironic.common import utils
from ironic.conductor import task_manager
from ironic.db import api as dbapi
from ironic.openstack.common import context
from ironic.tests import base
from ironic.tests.conductor import utils as mgr_utils
from ironic.tests.db import utils as db_utils
from ironic.tests.objects import utils as object_utils


CONF = cfg.CONF


class TestNeutron(base.TestCase):

    def setUp(self):
        super(TestNeutron, self).setUp()
        mgr_utils.mock_the_extension_manager(driver='fake')
        self.config(enabled_drivers=['fake'])
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
        self.dbapi = dbapi.get_instance()
        self.context = context.get_admin_context()
        self.node = object_utils.create_test_node(self.context)

    def _create_test_port(self, **kwargs):
        p = db_utils.get_test_port(**kwargs)
        return self.dbapi.create_port(p)

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
                    neutron_client_exc.NeutronClientException())
                self.assertRaises(
                        exception.FailedToUpdateDHCPOptOnPort,
                        api.update_port_dhcp_opts,
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
        api = neutron.NeutronAPI(my_context)
        mock_update_port.return_value = None
        api.update_port_address(port_id, address)
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
        api = neutron.NeutronAPI(my_context)
        mock_update_port.side_effect = (
                                neutron_client_exc.NeutronClientException())
        self.assertRaises(exception.FailedToUpdateMacOnPort,
                          api.update_port_address, port_id, address)

    def test_get_node_vif_ids_no_ports(self):
        expected = {}
        with task_manager.acquire(self.context, self.node.uuid) as task:
            result = neutron.get_node_vif_ids(task)
        self.assertEqual(expected, result)

    def test__get_node_vif_ids_one_port(self):
        port1 = self._create_test_port(node_id=self.node.id,
                                       id=6,
                                       address='aa:bb:cc',
                                       uuid=utils.generate_uuid(),
                                       extra={'vif_port_id': 'test-vif-A'},
                                       driver='fake')
        expected = {port1.uuid: 'test-vif-A'}
        with task_manager.acquire(self.context, self.node.uuid) as task:
            result = neutron.get_node_vif_ids(task)
        self.assertEqual(expected, result)

    def test__get_node_vif_ids_two_ports(self):
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
            result = neutron.get_node_vif_ids(task)
        self.assertEqual(expected, result)

    @mock.patch('ironic.common.neutron.NeutronAPI.update_port_dhcp_opts')
    @mock.patch('ironic.common.neutron.get_node_vif_ids')
    def test_update_neutron(self, mock_gnvi, mock_updo):
        opts = tftp.dhcp_options_for_instance(CONF.pxe.pxe_bootfile_name)
        mock_gnvi.return_value = {'port-uuid': 'vif-uuid'}
        with task_manager.acquire(self.context,
                                  self.node.uuid) as task:
            neutron.update_neutron(task, self.node)
        mock_updo.assertCalleOnceWith('vif-uuid', opts)

    @mock.patch('ironic.common.neutron.NeutronAPI.__init__')
    @mock.patch('ironic.common.neutron.get_node_vif_ids')
    def test_update_neutron_no_vif_data(self, mock_gnvi, mock_init):
        mock_gnvi.return_value = {}
        with task_manager.acquire(self.context,
                                  self.node.uuid) as task:
            neutron.update_neutron(task, self.node)
        mock_init.assert_not_called()

    @mock.patch('ironic.common.neutron.NeutronAPI.update_port_dhcp_opts')
    @mock.patch('ironic.common.neutron.get_node_vif_ids')
    def test_update_neutron_some_failures(self, mock_gnvi, mock_updo):
        # confirm update is called twice, one fails, but no exception raised
        mock_gnvi.return_value = {'p1': 'v1', 'p2': 'v2'}
        exc = exception.FailedToUpdateDHCPOptOnPort('fake exception')
        mock_updo.side_effect = [None, exc]
        with task_manager.acquire(self.context,
                                  self.node.uuid) as task:
            neutron.update_neutron(task, self.node)
        self.assertEqual(2, mock_updo.call_count)

    @mock.patch('ironic.common.neutron.NeutronAPI.update_port_dhcp_opts')
    @mock.patch('ironic.common.neutron.get_node_vif_ids')
    def test_update_neutron_fails(self, mock_gnvi, mock_updo):
        # confirm update is called twice, both fail, and exception is raised
        mock_gnvi.return_value = {'p1': 'v1', 'p2': 'v2'}
        exc = exception.FailedToUpdateDHCPOptOnPort('fake exception')
        mock_updo.side_effect = [exc, exc]
        with task_manager.acquire(self.context,
                                  self.node.uuid) as task:
            self.assertRaises(exception.FailedToUpdateDHCPOptOnPort,
                              neutron.update_neutron,
                              task, self.node)
        self.assertEqual(2, mock_updo.call_count)
