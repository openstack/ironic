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
from oslo_config import cfg
from oslo_utils import uuidutils

from ironic.common import exception
from ironic.common import neutron
from ironic.conductor import task_manager
# from ironic.conf import auth as ironic_auth
from ironic.tests import base
from ironic.tests.unit.conductor import mgr_utils
from ironic.tests.unit.db import base as db_base
from ironic.tests.unit.objects import utils as object_utils


@mock.patch.object(neutron, '_get_neutron_session')
@mock.patch.object(client.Client, "__init__")
class TestNeutronClient(base.TestCase):

    def setUp(self):
        super(TestNeutronClient, self).setUp()
        self.config(url_timeout=30,
                    retries=2,
                    group='neutron')
        self.config(admin_user='test-admin-user',
                    admin_tenant_name='test-admin-tenant',
                    admin_password='test-admin-password',
                    auth_uri='test-auth-uri',
                    group='keystone_authtoken')
        # TODO(pas-ha) register session options to test legacy path
        self.config(insecure=False,
                    cafile='test-file',
                    group='neutron')

    def test_get_neutron_client_with_token(self, mock_client_init,
                                           mock_session):
        token = 'test-token-123'
        sess = mock.Mock()
        sess.get_endpoint.return_value = 'fake-url'
        mock_session.return_value = sess
        expected = {'timeout': 30,
                    'retries': 2,
                    'insecure': False,
                    'ca_cert': 'test-file',
                    'token': token,
                    'endpoint_url': 'fake-url'}

        mock_client_init.return_value = None
        neutron.get_client(token=token)
        mock_client_init.assert_called_once_with(**expected)

    def test_get_neutron_client_without_token(self, mock_client_init,
                                              mock_session):
        self.config(url='test-url',
                    group='neutron')
        sess = mock.Mock()
        mock_session.return_value = sess
        expected = {'retries': 2,
                    'endpoint_override': 'test-url',
                    'session': sess}
        mock_client_init.return_value = None
        neutron.get_client(token=None)
        mock_client_init.assert_called_once_with(**expected)

    def test_get_neutron_client_with_region(self, mock_client_init,
                                            mock_session):
        self.config(region_name='fake_region',
                    group='keystone')
        sess = mock.Mock()
        mock_session.return_value = sess
        expected = {'retries': 2,
                    'region_name': 'fake_region',
                    'session': sess}

        mock_client_init.return_value = None
        neutron.get_client(token=None)
        mock_client_init.assert_called_once_with(**expected)

    def test_get_neutron_client_noauth(self, mock_client_init, mock_session):
        self.config(auth_strategy='noauth',
                    url='test-url',
                    group='neutron')
        expected = {'ca_cert': 'test-file',
                    'insecure': False,
                    'endpoint_url': 'test-url',
                    'timeout': 30,
                    'retries': 2,
                    'auth_strategy': 'noauth'}

        mock_client_init.return_value = None
        neutron.get_client(token=None)
        mock_client_init.assert_called_once_with(**expected)

    def test_out_range_auth_strategy(self, mock_client_init, mock_session):
        self.assertRaises(ValueError, cfg.CONF.set_override,
                          'auth_strategy', 'fake', 'neutron',
                          enforce_type=True)


class TestNeutronNetworkActions(db_base.DbTestCase):

    _CLIENT_ID = (
        '20:00:55:04:01:fe:80:00:00:00:00:00:00:00:02:c9:02:00:23:13:92')

    def setUp(self):
        super(TestNeutronNetworkActions, self).setUp()
        mgr_utils.mock_the_extension_manager(driver='fake')
        self.config(enabled_drivers=['fake'])
        self.node = object_utils.create_test_node(self.context)
        self.ports = [object_utils.create_test_port(
            self.context, node_id=self.node.id,
            uuid='1be26c0b-03f2-4d2e-ae87-c02d7f33c782',
            address='52:54:00:cf:2d:32',
            extra={'vif_port_id': uuidutils.generate_uuid()}
        )]
        # Very simple neutron port representation
        self.neutron_port = {'id': '132f871f-eaec-4fed-9475-0d54465e0f00',
                             'mac_address': '52:54:00:cf:2d:32'}
        self.network_uuid = uuidutils.generate_uuid()
        self.client_mock = mock.Mock()
        patcher = mock.patch('ironic.common.neutron.get_client',
                             return_value=self.client_mock)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _test_add_ports_to_vlan_network(self, is_client_id):
        # Ports will be created only if pxe_enabled is True
        object_utils.create_test_port(
            self.context, node_id=self.node.id,
            uuid=uuidutils.generate_uuid(),
            address='52:54:00:cf:2d:22',
            pxe_enabled=False
        )
        port = self.ports[0]
        if is_client_id:
            extra = port.extra
            extra['client-id'] = self._CLIENT_ID
            port.extra = extra
            port.save()
        expected_body = {
            'port': {
                'network_id': self.network_uuid,
                'admin_state_up': True,
                'binding:vnic_type': 'baremetal',
                'device_owner': 'baremetal:none',
                'binding:host_id': self.node.uuid,
                'device_id': self.node.uuid,
                'mac_address': port.address,
                'binding:profile': {
                    'local_link_information': [port.local_link_connection]
                }
            }
        }
        if is_client_id:
            expected_body['port']['extra_dhcp_opts'] = (
                [{'opt_name': 'client-id', 'opt_value': self._CLIENT_ID}])
        # Ensure we can create ports
        self.client_mock.create_port.return_value = {
            'port': self.neutron_port}
        expected = {port.uuid: self.neutron_port['id']}
        with task_manager.acquire(self.context, self.node.uuid) as task:
            ports = neutron.add_ports_to_network(task, self.network_uuid)
            self.assertEqual(expected, ports)
            self.client_mock.create_port.assert_called_once_with(
                expected_body)

    def test_add_ports_to_vlan_network(self):
        self._test_add_ports_to_vlan_network(is_client_id=False)

    def test_add_ports_with_client_id_to_vlan_network(self):
        self._test_add_ports_to_vlan_network(is_client_id=True)

    def _test_add_ports_to_flat_network(self, is_client_id):
        port = self.ports[0]
        if is_client_id:
            extra = port.extra
            extra['client-id'] = self._CLIENT_ID
            port.extra = extra
            port.save()
        expected_body = {
            'port': {
                'network_id': self.network_uuid,
                'admin_state_up': True,
                'binding:vnic_type': 'baremetal',
                'device_owner': 'baremetal:none',
                'device_id': self.node.uuid,
                'mac_address': port.address,
                'binding:profile': {
                    'local_link_information': [port.local_link_connection]
                }
            }
        }
        if is_client_id:
            expected_body['port']['extra_dhcp_opts'] = (
                [{'opt_name': 'client-id', 'opt_value': self._CLIENT_ID}])
        # Ensure we can create ports
        self.client_mock.create_port.return_value = {
            'port': self.neutron_port}
        expected = {port.uuid: self.neutron_port['id']}
        with task_manager.acquire(self.context, self.node.uuid) as task:
            ports = neutron.add_ports_to_network(task, self.network_uuid,
                                                 is_flat=True)
            self.assertEqual(expected, ports)
            self.client_mock.create_port.assert_called_once_with(
                expected_body)

    def test_add_ports_to_flat_network(self):
        self._test_add_ports_to_flat_network(is_client_id=False)

    def test_add_ports_with_client_id_to_flat_network(self):
        self._test_add_ports_to_flat_network(is_client_id=True)

    def test_add_ports_to_vlan_network_instance_uuid(self):
        self.node.instance_uuid = uuidutils.generate_uuid()
        self.node.save()
        port = self.ports[0]
        expected_body = {
            'port': {
                'network_id': self.network_uuid,
                'admin_state_up': True,
                'binding:vnic_type': 'baremetal',
                'device_owner': 'baremetal:none',
                'binding:host_id': self.node.uuid,
                'device_id': self.node.instance_uuid,
                'mac_address': port.address,
                'binding:profile': {
                    'local_link_information': [port.local_link_connection]
                }
            }
        }
        # Ensure we can create ports
        self.client_mock.create_port.return_value = {'port': self.neutron_port}
        expected = {port.uuid: self.neutron_port['id']}
        with task_manager.acquire(self.context, self.node.uuid) as task:
            ports = neutron.add_ports_to_network(task, self.network_uuid)
            self.assertEqual(expected, ports)
            self.client_mock.create_port.assert_called_once_with(expected_body)

    @mock.patch.object(neutron, 'rollback_ports')
    def test_add_network_all_ports_fail(self, rollback_mock):
        # Check that if creating a port fails, the ports are cleaned up
        self.client_mock.create_port.side_effect = \
            neutron_client_exc.ConnectionFailed

        with task_manager.acquire(self.context, self.node.uuid) as task:
            self.assertRaises(
                exception.NetworkError, neutron.add_ports_to_network, task,
                self.network_uuid)
            rollback_mock.assert_called_once_with(task, self.network_uuid)

    @mock.patch.object(neutron, 'LOG')
    def test_add_network_create_some_ports_fail(self, log_mock):
        object_utils.create_test_port(
            self.context, node_id=self.node.id,
            uuid=uuidutils.generate_uuid(),
            address='52:54:55:cf:2d:32',
            extra={'vif_port_id': uuidutils.generate_uuid()}
        )
        self.client_mock.create_port.side_effect = [
            {'port': self.neutron_port}, neutron_client_exc.ConnectionFailed]
        with task_manager.acquire(self.context, self.node.uuid) as task:
            neutron.add_ports_to_network(task, self.network_uuid)
            self.assertIn("Could not create neutron port for node's",
                          log_mock.warning.call_args_list[0][0][0])
            self.assertIn("Some errors were encountered when updating",
                          log_mock.warning.call_args_list[1][0][0])

    @mock.patch.object(neutron, 'remove_neutron_ports')
    def test_remove_ports_from_network(self, remove_mock):
        with task_manager.acquire(self.context, self.node.uuid) as task:
            neutron.remove_ports_from_network(task, self.network_uuid)
            remove_mock.assert_called_once_with(
                task,
                {'network_id': self.network_uuid,
                 'mac_address': [self.ports[0].address]}
            )

    @mock.patch.object(neutron, 'remove_neutron_ports')
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

    def test_remove_neutron_ports(self):
        with task_manager.acquire(self.context, self.node.uuid) as task:
            self.client_mock.list_ports.return_value = {
                'ports': [self.neutron_port]}
            neutron.remove_neutron_ports(task, {'param': 'value'})
        self.client_mock.list_ports.assert_called_once_with(
            **{'param': 'value'})
        self.client_mock.delete_port.assert_called_once_with(
            self.neutron_port['id'])

    def test_remove_neutron_ports_list_fail(self):
        with task_manager.acquire(self.context, self.node.uuid) as task:
            self.client_mock.list_ports.side_effect = \
                neutron_client_exc.ConnectionFailed
            self.assertRaisesRegex(
                exception.NetworkError, 'Could not get given network VIF',
                neutron.remove_neutron_ports, task, {'param': 'value'})
        self.client_mock.list_ports.assert_called_once_with(
            **{'param': 'value'})

    def test_remove_neutron_ports_delete_fail(self):
        with task_manager.acquire(self.context, self.node.uuid) as task:
            self.client_mock.delete_port.side_effect = \
                neutron_client_exc.ConnectionFailed
            self.client_mock.list_ports.return_value = {
                'ports': [self.neutron_port]}
            self.assertRaisesRegex(
                exception.NetworkError, 'Could not remove VIF',
                neutron.remove_neutron_ports, task, {'param': 'value'})
        self.client_mock.list_ports.assert_called_once_with(
            **{'param': 'value'})
        self.client_mock.delete_port.assert_called_once_with(
            self.neutron_port['id'])

    def test_get_node_portmap(self):
        with task_manager.acquire(self.context, self.node.uuid) as task:
            portmap = neutron.get_node_portmap(task)
            self.assertEqual(
                {self.ports[0].uuid: self.ports[0].local_link_connection},
                portmap
            )

    @mock.patch.object(neutron, 'remove_ports_from_network')
    def test_rollback_ports(self, remove_mock):
        with task_manager.acquire(self.context, self.node.uuid) as task:
            neutron.rollback_ports(task, self.network_uuid)
            remove_mock.assert_called_once_with(task, self.network_uuid)

    @mock.patch.object(neutron, 'LOG')
    @mock.patch.object(neutron, 'remove_ports_from_network')
    def test_rollback_ports_exception(self, remove_mock, log_mock):
        remove_mock.side_effect = exception.NetworkError('boom')
        with task_manager.acquire(self.context, self.node.uuid) as task:
            neutron.rollback_ports(task, self.network_uuid)
            self.assertTrue(log_mock.exception.called)
