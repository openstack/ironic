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

import time

from keystoneauth1 import loading as kaloading
import mock
from neutronclient.common import exceptions as neutron_client_exc
from neutronclient.v2_0 import client
from oslo_utils import uuidutils

from ironic.common import context
from ironic.common import exception
from ironic.common import neutron
from ironic.conductor import task_manager
from ironic.tests import base
from ironic.tests.unit.db import base as db_base
from ironic.tests.unit.objects import utils as object_utils


@mock.patch('ironic.common.keystone.get_service_auth', autospec=True,
            return_value=mock.sentinel.sauth)
@mock.patch('ironic.common.keystone.get_auth', autospec=True,
            return_value=mock.sentinel.auth)
@mock.patch('ironic.common.keystone.get_adapter', autospec=True)
@mock.patch('ironic.common.keystone.get_session', autospec=True,
            return_value=mock.sentinel.session)
@mock.patch.object(client.Client, "__init__", return_value=None, autospec=True)
class TestNeutronClient(base.TestCase):

    def setUp(self):
        super(TestNeutronClient, self).setUp()
        # NOTE(pas-ha) register keystoneauth dynamic options manually
        plugin = kaloading.get_plugin_loader('password')
        opts = kaloading.get_auth_plugin_conf_options(plugin)
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
        client_mock.assert_called_once_with(mock.ANY,  # this is 'self'
                                            session=mock.sentinel.session,
                                            auth=auth, retries=2,
                                            endpoint_override=url,
                                            global_request_id='global',
                                            timeout=45)

    @mock.patch('ironic.common.context.RequestContext', autospec=True)
    def test_get_neutron_client_with_token(self, mock_ctxt, mock_client_init,
                                           mock_session, mock_adapter,
                                           mock_auth, mock_sauth):
        mock_ctxt.return_value = ctxt = mock.Mock()
        ctxt.auth_token = 'test-token-123'
        mock_adapter.return_value = adapter = mock.Mock()
        adapter.get_endpoint.return_value = 'neutron_url'
        neutron.get_client(token='test-token-123')
        mock_ctxt.assert_called_once_with(auth_token='test-token-123')
        mock_client_init.assert_called_once_with(
            mock.ANY,  # this is 'self'
            session=mock.sentinel.session,
            auth=mock.sentinel.sauth,
            retries=2,
            endpoint_override='neutron_url',
            global_request_id=ctxt.global_id,
            timeout=45)

        # testing handling of default url_timeout
        mock_session.assert_called_once_with('neutron', timeout=10)
        mock_adapter.assert_called_once_with('neutron',
                                             session=mock.sentinel.session,
                                             auth=mock.sentinel.auth)
        mock_sauth.assert_called_once_with(mock_ctxt.return_value,
                                           'neutron_url', mock.sentinel.auth)

    def test_get_neutron_client_with_context(self, mock_client_init,
                                             mock_session, mock_adapter,
                                             mock_auth, mock_sauth):
        self.context = context.RequestContext(global_request_id='global',
                                              auth_token='test-token-123')
        mock_adapter.return_value = adapter = mock.Mock()
        adapter.get_endpoint.return_value = 'neutron_url'
        self._call_and_assert_client(mock_client_init, 'neutron_url',
                                     auth=mock.sentinel.sauth)
        # testing handling of default url_timeout
        mock_session.assert_called_once_with('neutron', timeout=10)
        mock_adapter.assert_called_once_with('neutron',
                                             session=mock.sentinel.session,
                                             auth=mock.sentinel.auth)
        mock_sauth.assert_called_once_with(self.context, 'neutron_url',
                                           mock.sentinel.auth)

    def test_get_neutron_client_without_token(self, mock_client_init,
                                              mock_session, mock_adapter,
                                              mock_auth, mock_sauth):
        mock_adapter.return_value = adapter = mock.Mock()
        adapter.get_endpoint.return_value = 'neutron_url'
        self._call_and_assert_client(mock_client_init, 'neutron_url')
        mock_session.assert_called_once_with('neutron', timeout=10)
        mock_adapter.assert_called_once_with('neutron',
                                             session=mock.sentinel.session,
                                             auth=mock.sentinel.auth)
        self.assertEqual(0, mock_sauth.call_count)

    def test_get_neutron_client_noauth(self, mock_client_init, mock_session,
                                       mock_adapter, mock_auth, mock_sauth):
        self.config(endpoint_override='neutron_url',
                    auth_type='none',
                    timeout=10,
                    group='neutron')
        mock_adapter.return_value = adapter = mock.Mock()
        adapter.get_endpoint.return_value = 'neutron_url'

        self._call_and_assert_client(mock_client_init, 'neutron_url')

        self.assertEqual('none', neutron.CONF.neutron.auth_type)
        mock_session.assert_called_once_with('neutron', timeout=10)
        mock_adapter.assert_called_once_with('neutron',
                                             session=mock.sentinel.session,
                                             auth=mock.sentinel.auth)
        mock_auth.assert_called_once_with('neutron')
        self.assertEqual(0, mock_sauth.call_count)


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
        # Very simple neutron port representation
        self.neutron_port = {'id': '132f871f-eaec-4fed-9475-0d54465e0f00',
                             'mac_address': '52:54:00:cf:2d:32'}
        self.network_uuid = uuidutils.generate_uuid()
        self.client_mock = mock.Mock()
        self.client_mock.list_agents.return_value = {
            'agents': [{'alive': True}]}
        patcher = mock.patch('ironic.common.neutron.get_client',
                             return_value=self.client_mock, autospec=True)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _test_add_ports_to_network(self, is_client_id,
                                   security_groups=None):
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
        if security_groups:
            expected_body['port']['security_groups'] = security_groups

        if is_client_id:
            expected_body['port']['extra_dhcp_opts'] = (
                [{'opt_name': '61', 'opt_value': self._CLIENT_ID}])
        # Ensure we can create ports
        self.client_mock.create_port.return_value = {
            'port': self.neutron_port}
        expected = {port.uuid: self.neutron_port['id']}
        with task_manager.acquire(self.context, self.node.uuid) as task:
            ports = neutron.add_ports_to_network(
                task, self.network_uuid, security_groups=security_groups)
            self.assertEqual(expected, ports)
            self.client_mock.create_port.assert_called_once_with(
                expected_body)

    def test_add_ports_to_network(self):
        self._test_add_ports_to_network(is_client_id=False,
                                        security_groups=None)

    @mock.patch.object(neutron, '_verify_security_groups', autospec=True)
    def test_add_ports_to_network_with_sg(self, verify_mock):
        sg_ids = []
        for i in range(2):
            sg_ids.append(uuidutils.generate_uuid())
        self._test_add_ports_to_network(is_client_id=False,
                                        security_groups=sg_ids)

    def test_verify_sec_groups(self):
        sg_ids = []
        for i in range(2):
            sg_ids.append(uuidutils.generate_uuid())

        expected_vals = {'security_groups': []}
        for sg in sg_ids:
            expected_vals['security_groups'].append({'id': sg})

        client = mock.MagicMock()
        client.list_security_groups.return_value = expected_vals

        self.assertIsNone(
            neutron._verify_security_groups(sg_ids, client))
        client.list_security_groups.assert_called_once_with()

    def test_verify_sec_groups_less_than_configured(self):
        sg_ids = []
        for i in range(2):
            sg_ids.append(uuidutils.generate_uuid())

        expected_vals = {'security_groups': []}
        for sg in sg_ids:
            expected_vals['security_groups'].append({'id': sg})

        client = mock.MagicMock()
        client.list_security_groups.return_value = expected_vals

        self.assertIsNone(
            neutron._verify_security_groups(sg_ids[:1], client))
        client.list_security_groups.assert_called_once_with()

    def test_verify_sec_groups_more_than_configured(self):
        sg_ids = []
        for i in range(1):
            sg_ids.append(uuidutils.generate_uuid())

        client = mock.MagicMock()
        expected_vals = {'security_groups': []}
        client.list_security_groups.return_value = expected_vals

        self.assertRaises(
            exception.NetworkError,
            neutron._verify_security_groups, sg_ids, client)
        client.list_security_groups.assert_called_once_with()

    def test_verify_sec_groups_no_sg_from_neutron(self):
        sg_ids = []
        for i in range(1):
            sg_ids.append(uuidutils.generate_uuid())

        client = mock.MagicMock()
        client.list_security_groups.return_value = {}

        self.assertRaises(
            exception.NetworkError,
            neutron._verify_security_groups, sg_ids, client)
        client.list_security_groups.assert_called_once_with()

    def test_verify_sec_groups_exception_by_neutronclient(self):
        sg_ids = []
        for i in range(2):
            sg_ids.append(uuidutils.generate_uuid())

        client = mock.MagicMock()
        client.list_security_groups.side_effect = \
            neutron_client_exc.NeutronClientException

        self.assertRaisesRegex(
            exception.NetworkError,
            "Could not retrieve security groups",
            neutron._verify_security_groups, sg_ids, client)
        client.list_security_groups.assert_called_once_with()

    def test_add_ports_with_client_id_to_network(self):
        self._test_add_ports_to_network(is_client_id=True)

    @mock.patch.object(neutron, 'validate_port_info', autospec=True)
    def test_add_ports_to_network_instance_uuid(self, vpi_mock):
        self.node.instance_uuid = uuidutils.generate_uuid()
        self.node.network_interface = 'neutron'
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
        vpi_mock.return_value = True
        # Ensure we can create ports
        self.client_mock.create_port.return_value = {'port': self.neutron_port}
        expected = {port.uuid: self.neutron_port['id']}
        with task_manager.acquire(self.context, self.node.uuid) as task:
            ports = neutron.add_ports_to_network(task, self.network_uuid)
            self.assertEqual(expected, ports)
            self.client_mock.create_port.assert_called_once_with(expected_body)
        self.assertTrue(vpi_mock.called)

    @mock.patch.object(neutron, 'rollback_ports', autospec=True)
    def test_add_network_all_ports_fail(self, rollback_mock):
        # Check that if creating a port fails, the ports are cleaned up
        self.client_mock.create_port.side_effect = \
            neutron_client_exc.ConnectionFailed

        with task_manager.acquire(self.context, self.node.uuid) as task:
            self.assertRaises(
                exception.NetworkError, neutron.add_ports_to_network, task,
                self.network_uuid)
            rollback_mock.assert_called_once_with(task, self.network_uuid)

    @mock.patch.object(neutron, 'LOG', autospec=True)
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

    def test_remove_neutron_ports_delete_race(self):
        with task_manager.acquire(self.context, self.node.uuid) as task:
            self.client_mock.delete_port.side_effect = \
                neutron_client_exc.PortNotFoundClient
            self.client_mock.list_ports.return_value = {
                'ports': [self.neutron_port]}
            neutron.remove_neutron_ports(task, {'param': 'value'})
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

    def test_validate_agent_up(self):
        self.client_mock.list_agents.return_value = {
            'agents': [{'alive': True}]}
        self.assertTrue(neutron._validate_agent(self.client_mock))

    def test_validate_agent_down(self):
        self.client_mock.list_agents.return_value = {
            'agents': [{'alive': False}]}
        self.assertFalse(neutron._validate_agent(self.client_mock))

    def test_is_smartnic_port_true(self):
        port = self.ports[0]
        port.is_smartnic = True
        self.assertTrue(neutron.is_smartnic_port(port))

    def test_is_smartnic_port_false(self):
        port = self.ports[0]
        self.assertFalse(neutron.is_smartnic_port(port))

    @mock.patch.object(neutron, '_validate_agent')
    @mock.patch.object(time, 'sleep')
    def test_wait_for_host_agent_up_target_state_up(
            self, sleep_mock, validate_agent_mock):
        validate_agent_mock.return_value = True
        self.assertTrue(neutron.wait_for_host_agent(
            self.client_mock, 'hostname'))
        sleep_mock.assert_not_called()

    @mock.patch.object(neutron, '_validate_agent')
    @mock.patch.object(time, 'sleep')
    def test_wait_for_host_agent_down_target_state_up(
            self, sleep_mock, validate_agent_mock):
        validate_agent_mock.return_value = False
        self.assertRaises(exception.NetworkError,
                          neutron.wait_for_host_agent,
                          self.client_mock, 'hostname')

    @mock.patch.object(neutron, '_validate_agent')
    @mock.patch.object(time, 'sleep')
    def test_wait_for_host_agent_up_target_state_down(
            self, sleep_mock, validate_agent_mock):
        validate_agent_mock.return_value = True
        self.assertRaises(exception.NetworkError,
                          neutron.wait_for_host_agent,
                          self.client_mock, 'hostname', target_state='down')

    @mock.patch.object(neutron, '_validate_agent')
    @mock.patch.object(time, 'sleep')
    def test_wait_for_host_agent_down_target_state_down(
            self, sleep_mock, validate_agent_mock):
        validate_agent_mock.return_value = False
        self.assertTrue(
            neutron.wait_for_host_agent(self.client_mock, 'hostname',
                                        target_state='down'))
        sleep_mock.assert_not_called()

    @mock.patch.object(neutron, '_get_port_by_uuid')
    @mock.patch.object(time, 'sleep')
    def test_wait_for_port_status_up(self, sleep_mock, get_port_mock):
        get_port_mock.return_value = {'status': 'ACTIVE'}
        neutron.wait_for_port_status(self.client_mock, 'port_id', 'ACTIVE')
        sleep_mock.assert_not_called()

    @mock.patch.object(neutron, '_get_port_by_uuid')
    @mock.patch.object(time, 'sleep')
    def test_wait_for_port_status_down(self, sleep_mock, get_port_mock):
        get_port_mock.side_effect = [{'status': 'DOWN'}, {'status': 'ACTIVE'}]
        neutron.wait_for_port_status(self.client_mock, 'port_id', 'ACTIVE')
        sleep_mock.assert_called_once()

    @mock.patch.object(neutron, '_get_port_by_uuid')
    @mock.patch.object(time, 'sleep')
    def test_wait_for_port_status_active_max_retry(self, sleep_mock,
                                                   get_port_mock):
        get_port_mock.return_value = {'status': 'DOWN'}
        self.assertRaises(exception.NetworkError,
                          neutron.wait_for_port_status,
                          self.client_mock, 'port_id', 'ACTIVE')

    @mock.patch.object(neutron, '_get_port_by_uuid')
    @mock.patch.object(time, 'sleep')
    def test_wait_for_port_status_down_max_retry(self, sleep_mock,
                                                 get_port_mock):
        get_port_mock.return_value = {'status': 'ACTIVE'}
        self.assertRaises(exception.NetworkError,
                          neutron.wait_for_port_status,
                          self.client_mock, 'port_id', 'DOWN')

    @mock.patch.object(neutron, 'wait_for_host_agent', autospec=True)
    @mock.patch.object(neutron, 'wait_for_port_status', autospec=True)
    def test_add_smartnic_port_to_network(
            self, wait_port_mock, wait_agent_mock):
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

        expected_body = {
            'port': {
                'network_id': self.network_uuid,
                'admin_state_up': True,
                'binding:vnic_type': 'smart-nic',
                'device_owner': 'baremetal:none',
                'binding:host_id': port.local_link_connection['hostname'],
                'device_id': self.node.uuid,
                'mac_address': port.address,
                'binding:profile': {
                    'local_link_information': [port.local_link_connection]
                }
            }
        }

        # Ensure we can create ports
        self.client_mock.create_port.return_value = {
            'port': self.neutron_port}
        expected = {port.uuid: self.neutron_port['id']}
        with task_manager.acquire(self.context, self.node.uuid) as task:
            ports = neutron.add_ports_to_network(task, self.network_uuid)
            self.assertEqual(expected, ports)
            self.client_mock.create_port.assert_called_once_with(
                expected_body)
            wait_agent_mock.assert_called_once_with(
                self.client_mock, 'hostname')
            wait_port_mock.assert_called_once_with(
                self.client_mock, self.neutron_port['id'], 'ACTIVE')

    @mock.patch.object(neutron, 'is_smartnic_port', autospec=True)
    @mock.patch.object(neutron, 'wait_for_host_agent', autospec=True)
    def test_remove_neutron_smartnic_ports(
            self, wait_agent_mock, is_smartnic_mock):
        with task_manager.acquire(self.context, self.node.uuid) as task:
            is_smartnic_mock.return_value = True
            self.neutron_port['binding:host_id'] = 'hostname'
            self.client_mock.list_ports.return_value = {
                'ports': [self.neutron_port]}
            neutron.remove_neutron_ports(task, {'param': 'value'})
        self.client_mock.list_ports.assert_called_once_with(
            **{'param': 'value'})
        self.client_mock.delete_port.assert_called_once_with(
            self.neutron_port['id'])
        is_smartnic_mock.assert_called_once_with(self.neutron_port)
        wait_agent_mock.assert_called_once_with(self.client_mock, 'hostname')


@mock.patch.object(neutron, 'get_client', autospec=True)
class TestValidateNetwork(base.TestCase):
    def setUp(self):
        super(TestValidateNetwork, self).setUp()

        self.uuid = uuidutils.generate_uuid()
        self.context = context.RequestContext()

    def test_by_uuid(self, client_mock):
        net_mock = client_mock.return_value.list_networks
        net_mock.return_value = {
            'networks': [
                {'id': self.uuid},
            ]
        }

        self.assertEqual(self.uuid, neutron.validate_network(
            self.uuid, context=self.context))
        net_mock.assert_called_once_with(fields=['id'],
                                         id=self.uuid)

    def test_by_name(self, client_mock):
        net_mock = client_mock.return_value.list_networks
        net_mock.return_value = {
            'networks': [
                {'id': self.uuid},
            ]
        }

        self.assertEqual(self.uuid, neutron.validate_network(
            'name', context=self.context))
        net_mock.assert_called_once_with(fields=['id'],
                                         name='name')

    def test_not_found(self, client_mock):
        net_mock = client_mock.return_value.list_networks
        net_mock.return_value = {
            'networks': []
        }

        self.assertRaisesRegex(exception.InvalidParameterValue,
                               'was not found',
                               neutron.validate_network,
                               self.uuid, context=self.context)
        net_mock.assert_called_once_with(fields=['id'],
                                         id=self.uuid)

    def test_failure(self, client_mock):
        net_mock = client_mock.return_value.list_networks
        net_mock.side_effect = neutron_client_exc.NeutronClientException('foo')

        self.assertRaisesRegex(exception.NetworkError, 'foo',
                               neutron.validate_network, 'name',
                               context=self.context)
        net_mock.assert_called_once_with(fields=['id'],
                                         name='name')

    def test_duplicate(self, client_mock):
        net_mock = client_mock.return_value.list_networks
        net_mock.return_value = {
            'networks': [{'id': self.uuid},
                         {'id': 'uuid2'}]
        }

        self.assertRaisesRegex(exception.InvalidParameterValue,
                               'More than one network',
                               neutron.validate_network, 'name',
                               context=self.context)
        net_mock.assert_called_once_with(fields=['id'],
                                         name='name')


@mock.patch.object(neutron, 'get_client', autospec=True)
class TestUpdatePortAddress(base.TestCase):

    def setUp(self):
        super(TestUpdatePortAddress, self).setUp()
        self.context = context.RequestContext()

    def test_update_port_address(self, mock_client):
        address = 'fe:54:00:77:07:d9'
        port_id = 'fake-port-id'
        expected = {'port': {'mac_address': address}}
        mock_client.return_value.show_port.return_value = {}

        neutron.update_port_address(port_id, address, context=self.context)
        mock_client.return_value.update_port.assert_called_once_with(port_id,
                                                                     expected)

    @mock.patch.object(neutron, 'unbind_neutron_port', autospec=True)
    def test_update_port_address_with_binding(self, mock_unp, mock_client):
        address = 'fe:54:00:77:07:d9'
        port_id = 'fake-port-id'

        mock_client.return_value.show_port.return_value = {
            'port': {'binding:host_id': 'host',
                     'binding:profile': 'foo'}}

        calls = [mock.call(port_id, {'port': {'mac_address': address}}),
                 mock.call(port_id, {'port': {'binding:host_id': 'host',
                                     'binding:profile': 'foo'}})]

        neutron.update_port_address(port_id, address, context=self.context)
        mock_unp.assert_called_once_with(
            port_id,
            client=mock_client(context=self.context),
            context=self.context)
        mock_client.return_value.update_port.assert_has_calls(calls)

    @mock.patch.object(neutron, 'unbind_neutron_port', autospec=True)
    def test_update_port_address_without_binding(self, mock_unp, mock_client):
        address = 'fe:54:00:77:07:d9'
        port_id = 'fake-port-id'
        expected = {'port': {'mac_address': address}}
        mock_client.return_value.show_port.return_value = {
            'port': {'binding:profile': 'foo'}}

        neutron.update_port_address(port_id, address, context=self.context)
        self.assertFalse(mock_unp.called)
        mock_client.return_value.update_port.assert_any_call(port_id, expected)

    def test_update_port_address_show_failed(self, mock_client):
        address = 'fe:54:00:77:07:d9'
        port_id = 'fake-port-id'
        mock_client.return_value.show_port.side_effect = (
            neutron_client_exc.NeutronClientException())

        self.assertRaises(exception.FailedToUpdateMacOnPort,
                          neutron.update_port_address,
                          port_id, address, context=self.context)
        self.assertFalse(mock_client.return_value.update_port.called)

    @mock.patch.object(neutron, 'unbind_neutron_port', autospec=True)
    def test_update_port_address_unbind_port_failed(self, mock_unp,
                                                    mock_client):
        address = 'fe:54:00:77:07:d9'
        port_id = 'fake-port-id'
        mock_client.return_value.show_port.return_value = {
            'port': {'binding:profile': 'foo',
                     'binding:host_id': 'host'}}
        mock_unp.side_effect = (exception.NetworkError('boom'))
        self.assertRaises(exception.FailedToUpdateMacOnPort,
                          neutron.update_port_address,
                          port_id, address, context=self.context)
        mock_unp.assert_called_once_with(
            port_id,
            client=mock_client(context=self.context),
            context=self.context)
        self.assertFalse(mock_client.return_value.update_port.called)

    @mock.patch.object(neutron, 'unbind_neutron_port', autospec=True)
    def test_update_port_address_with_exception(self, mock_unp,
                                                mock_client):
        address = 'fe:54:00:77:07:d9'
        port_id = 'fake-port-id'
        mock_client.return_value.show_port.return_value = {}
        mock_client.return_value.update_port.side_effect = (
            neutron_client_exc.NeutronClientException())

        self.assertRaises(exception.FailedToUpdateMacOnPort,
                          neutron.update_port_address,
                          port_id, address, context=self.context)


@mock.patch.object(neutron, 'get_client', autospec=True)
class TestUnbindPort(base.TestCase):

    def setUp(self):
        super(TestUnbindPort, self).setUp()
        self.context = context.RequestContext()

    def test_unbind_neutron_port_client_passed(self, mock_client):
        port_id = 'fake-port-id'
        body_unbind = {
            'port': {
                'binding:host_id': '',
                'binding:profile': {}
            }
        }
        body_reset_mac = {
            'port': {
                'mac_address': None
            }
        }
        update_calls = [
            mock.call(port_id, body_unbind),
            mock.call(port_id, body_reset_mac)
        ]
        neutron.unbind_neutron_port(port_id,
                                    mock_client(context=self.context),
                                    context=self.context)
        self.assertEqual(1, mock_client.call_count)
        mock_client.return_value.update_port.assert_has_calls(update_calls)

    @mock.patch.object(neutron, 'LOG', autospec=True)
    def test_unbind_neutron_port_failure(self, mock_log, mock_client):
        mock_client.return_value.update_port.side_effect = (
            neutron_client_exc.NeutronClientException())
        body = {
            'port': {
                'binding:host_id': '',
                'binding:profile': {}
            }
        }
        port_id = 'fake-port-id'
        self.assertRaises(exception.NetworkError, neutron.unbind_neutron_port,
                          port_id, context=self.context)
        mock_client.assert_called_once_with(context=self.context)
        mock_client.return_value.update_port.assert_called_once_with(port_id,
                                                                     body)
        mock_log.exception.assert_called_once()

    def test_unbind_neutron_port(self, mock_client):
        port_id = 'fake-port-id'
        body_unbind = {
            'port': {
                'binding:host_id': '',
                'binding:profile': {}
            }
        }
        body_reset_mac = {
            'port': {
                'mac_address': None
            }
        }
        update_calls = [
            mock.call(port_id, body_unbind),
            mock.call(port_id, body_reset_mac)
        ]
        neutron.unbind_neutron_port(port_id, context=self.context)
        mock_client.assert_called_once_with(context=self.context)
        mock_client.return_value.update_port.assert_has_calls(update_calls)

    @mock.patch.object(neutron, 'LOG', autospec=True)
    def test_unbind_neutron_port_not_found(self, mock_log, mock_client):
        port_id = 'fake-port-id'
        mock_client.return_value.update_port.side_effect = (
            neutron_client_exc.PortNotFoundClient())
        body = {
            'port': {
                'binding:host_id': '',
                'binding:profile': {}
            }
        }
        neutron.unbind_neutron_port(port_id, context=self.context)
        mock_client.assert_called_once_with(context=self.context)
        mock_client.return_value.update_port.assert_called_once_with(port_id,
                                                                     body)
        mock_log.info.assert_called_once_with('Port %s was not found while '
                                              'unbinding.', port_id)


class TestGetNetworkByUUIDOrName(base.TestCase):

    def setUp(self):
        super(TestGetNetworkByUUIDOrName, self).setUp()
        self.client = mock.MagicMock()

    def test__get_network_by_uuid_or_name_uuid(self):
        network_uuid = '9acb0256-2c1b-420a-b9d7-62bee90b6ed7'
        networks = {
            'networks': [{
                'field1': 'value1',
                'field2': 'value2',
            }],
        }
        fields = ['field1', 'field2']
        self.client.list_networks.return_value = networks
        result = neutron._get_network_by_uuid_or_name(
            self.client, network_uuid, fields=fields)
        self.client.list_networks.assert_called_once_with(
            id=network_uuid, fields=fields)
        self.assertEqual(networks['networks'][0], result)

    def test__get_network_by_uuid_or_name_name(self):
        network_name = 'test-net'
        networks = {
            'networks': [{
                'field1': 'value1',
                'field2': 'value2',
            }],
        }
        fields = ['field1', 'field2']
        self.client.list_networks.return_value = networks
        result = neutron._get_network_by_uuid_or_name(
            self.client, network_name, fields=fields)
        self.client.list_networks.assert_called_once_with(
            name=network_name, fields=fields)
        self.assertEqual(networks['networks'][0], result)

    def test__get_network_by_uuid_or_name_failure(self):
        network_uuid = '9acb0256-2c1b-420a-b9d7-62bee90b6ed7'
        self.client.list_networks.side_effect = (
            neutron_client_exc.NeutronClientException())
        self.assertRaises(exception.NetworkError,
                          neutron._get_network_by_uuid_or_name,
                          self.client, network_uuid)
        self.client.list_networks.assert_called_once_with(id=network_uuid)

    def test__get_network_by_uuid_or_name_missing(self):
        network_uuid = '9acb0256-2c1b-420a-b9d7-62bee90b6ed7'
        networks = {
            'networks': [],
        }
        self.client.list_networks.return_value = networks
        self.assertRaises(exception.InvalidParameterValue,
                          neutron._get_network_by_uuid_or_name,
                          self.client, network_uuid)
        self.client.list_networks.assert_called_once_with(id=network_uuid)

    def test__get_network_by_uuid_or_name_duplicate(self):
        network_name = 'test-net'
        networks = {
            'networks': [
                {'id': '9acb0256-2c1b-420a-b9d7-62bee90b6ed7'},
                {'id': '9014b6a7-8291-4676-80b0-ab00988ce3c7'},
            ],
        }
        self.client.list_networks.return_value = networks
        self.assertRaises(exception.InvalidParameterValue,
                          neutron._get_network_by_uuid_or_name,
                          self.client, network_name)
        self.client.list_networks.assert_called_once_with(name=network_name)


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
        mock_gp.return_value = {
            'network_id': network_uuid,
        }
        mock_gn.return_value = {
            'provider:physical_network': physnet,
        }
        result = neutron.get_physnets_by_port_uuid(self.client,
                                                   port_uuid)
        mock_gp.assert_called_once_with(self.client, port_uuid,
                                        fields=self.PORT_FIELDS)
        mock_gn.assert_called_once_with(self.client, network_uuid,
                                        fields=self.NETWORK_FIELDS)
        self.assertEqual({physnet}, result)

    def test_get_physnets_by_port_uuid_single_segment_no_physnet(
            self, mock_gp, mock_gn):
        port_uuid = 'fake-port-uuid'
        network_uuid = 'fake-network-uuid'
        mock_gp.return_value = {
            'network_id': network_uuid,
        }
        mock_gn.return_value = {
            'provider:physical_network': None,
        }
        result = neutron.get_physnets_by_port_uuid(self.client,
                                                   port_uuid)
        mock_gp.assert_called_once_with(self.client, port_uuid,
                                        fields=self.PORT_FIELDS)
        mock_gn.assert_called_once_with(self.client, network_uuid,
                                        fields=self.NETWORK_FIELDS)
        self.assertEqual(set(), result)

    def test_get_physnets_by_port_uuid_multiple_segments(self, mock_gp,
                                                         mock_gn):
        port_uuid = 'fake-port-uuid'
        network_uuid = 'fake-network-uuid'
        physnet1 = 'fake-physnet-1'
        physnet2 = 'fake-physnet-2'
        mock_gp.return_value = {
            'network_id': network_uuid,
        }
        mock_gn.return_value = {
            'segments': [
                {
                    'provider:physical_network': physnet1,
                },
                {
                    'provider:physical_network': physnet2,
                },
            ],
        }
        result = neutron.get_physnets_by_port_uuid(self.client,
                                                   port_uuid)
        mock_gp.assert_called_once_with(self.client, port_uuid,
                                        fields=self.PORT_FIELDS)
        mock_gn.assert_called_once_with(self.client, network_uuid,
                                        fields=self.NETWORK_FIELDS)
        self.assertEqual({physnet1, physnet2}, result)

    def test_get_physnets_by_port_uuid_multiple_segments_no_physnet(
            self, mock_gp, mock_gn):
        port_uuid = 'fake-port-uuid'
        network_uuid = 'fake-network-uuid'
        mock_gp.return_value = {
            'network_id': network_uuid,
        }
        mock_gn.return_value = {
            'segments': [
                {
                    'provider:physical_network': None,
                },
                {
                    'provider:physical_network': None,
                },
            ],
        }
        result = neutron.get_physnets_by_port_uuid(self.client,
                                                   port_uuid)
        mock_gp.assert_called_once_with(self.client, port_uuid,
                                        fields=self.PORT_FIELDS)
        mock_gn.assert_called_once_with(self.client, network_uuid,
                                        fields=self.NETWORK_FIELDS)
        self.assertEqual(set(), result)

    def test_get_physnets_by_port_uuid_port_missing(self, mock_gp, mock_gn):
        port_uuid = 'fake-port-uuid'
        mock_gp.side_effect = exception.InvalidParameterValue('error')
        self.assertRaises(exception.InvalidParameterValue,
                          neutron.get_physnets_by_port_uuid,
                          self.client, port_uuid)
        mock_gp.assert_called_once_with(self.client, port_uuid,
                                        fields=self.PORT_FIELDS)
        self.assertFalse(mock_gn.called)

    def test_get_physnets_by_port_uuid_port_failure(self, mock_gp, mock_gn):
        port_uuid = 'fake-port-uuid'
        mock_gp.side_effect = exception.NetworkError
        self.assertRaises(exception.NetworkError,
                          neutron.get_physnets_by_port_uuid,
                          self.client, port_uuid)
        mock_gp.assert_called_once_with(self.client, port_uuid,
                                        fields=self.PORT_FIELDS)
        self.assertFalse(mock_gn.called)

    def test_get_physnets_by_port_uuid_network_missing(
            self, mock_gp, mock_gn):
        port_uuid = 'fake-port-uuid'
        network_uuid = 'fake-network-uuid'
        mock_gp.return_value = {
            'network_id': network_uuid,
        }
        mock_gn.side_effect = exception.InvalidParameterValue('error')
        self.assertRaises(exception.InvalidParameterValue,
                          neutron.get_physnets_by_port_uuid,
                          self.client, port_uuid)
        mock_gp.assert_called_once_with(self.client, port_uuid,
                                        fields=self.PORT_FIELDS)
        mock_gn.assert_called_once_with(self.client, network_uuid,
                                        fields=self.NETWORK_FIELDS)

    def test_get_physnets_by_port_uuid_network_failure(
            self, mock_gp, mock_gn):
        port_uuid = 'fake-port-uuid'
        network_uuid = 'fake-network-uuid'
        mock_gp.return_value = {
            'network_id': network_uuid,
        }
        mock_gn.side_effect = exception.NetworkError
        self.assertRaises(exception.NetworkError,
                          neutron.get_physnets_by_port_uuid,
                          self.client, port_uuid)
        mock_gp.assert_called_once_with(self.client, port_uuid,
                                        fields=self.PORT_FIELDS)
        mock_gn.assert_called_once_with(self.client, network_uuid,
                                        fields=self.NETWORK_FIELDS)
