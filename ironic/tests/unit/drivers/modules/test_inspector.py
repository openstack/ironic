# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

from unittest import mock

import eventlet
from keystoneauth1 import exceptions as ks_exception
import openstack

from ironic.common import context
from ironic.common import exception
from ironic.common import states
from ironic.common import utils
from ironic.conductor import task_manager
from ironic.drivers.modules import inspect_utils
from ironic.drivers.modules import inspector
from ironic.drivers.modules.redfish import utils as redfish_utils
from ironic.tests.unit.db import base as db_base
from ironic.tests.unit.objects import utils as obj_utils

CONF = inspector.CONF


@mock.patch('ironic.common.keystone.get_auth', autospec=True,
            return_value=mock.sentinel.auth)
@mock.patch('ironic.common.keystone.get_session', autospec=True,
            return_value=mock.sentinel.session)
@mock.patch.object(openstack.connection, 'Connection', autospec=True)
class GetClientTestCase(db_base.DbTestCase):

    def setUp(self):
        super(GetClientTestCase, self).setUp()
        # NOTE(pas-ha) force-reset  global inspector session object
        inspector._INSPECTOR_SESSION = None
        self.context = context.RequestContext(global_request_id='global')

    def test__get_client(self, mock_conn, mock_session, mock_auth):
        inspector._get_client(self.context)
        mock_conn.assert_called_once_with(
            session=mock.sentinel.session,
            oslo_conf=mock.ANY)
        self.assertEqual(1, mock_auth.call_count)
        self.assertEqual(1, mock_session.call_count)

    def test__get_client_standalone(self, mock_conn, mock_session, mock_auth):
        self.config(auth_strategy='noauth')
        inspector._get_client(self.context)
        self.assertEqual('none', inspector.CONF.inspector.auth_type)
        mock_conn.assert_called_once_with(
            session=mock.sentinel.session,
            oslo_conf=mock.ANY)
        self.assertEqual(1, mock_auth.call_count)
        self.assertEqual(1, mock_session.call_count)

    def test__get_client_connection_problem(
            self, mock_conn, mock_session, mock_auth):
        mock_conn.side_effect = ks_exception.DiscoveryFailure("")
        self.assertRaises(exception.ConfigInvalid,
                          inspector._get_client, self.context)
        mock_conn.assert_called_once_with(
            session=mock.sentinel.session,
            oslo_conf=mock.ANY)
        self.assertEqual(1, mock_auth.call_count)
        self.assertEqual(1, mock_session.call_count)


class BaseTestCase(db_base.DbTestCase):
    def setUp(self):
        super(BaseTestCase, self).setUp()
        self.node = obj_utils.create_test_node(self.context,
                                               inspect_interface='inspector')
        self.iface = inspector.Inspector()
        self.task = mock.MagicMock(spec=task_manager.TaskManager)
        self.task.context = self.context
        self.task.shared = False
        self.task.node = self.node
        self.task.driver = mock.Mock(
            spec=['boot', 'network', 'inspect', 'power', 'management'],
            inspect=self.iface)
        self.driver = self.task.driver


class CommonFunctionsTestCase(BaseTestCase):
    def test_validate_ok(self):
        self.iface.validate(self.task)

    def test_get_properties(self):
        res = self.iface.get_properties()
        self.assertEqual({}, res)

    def test_get_callback_endpoint(self):
        for catalog_endp in ['http://192.168.0.42:5050',
                             'http://192.168.0.42:5050/v1',
                             'http://192.168.0.42:5050/']:
            client = mock.Mock()
            client.get_endpoint.return_value = catalog_endp
            self.assertEqual('http://192.168.0.42:5050/v1/continue',
                             inspector._get_callback_endpoint(client))

    def test_get_callback_endpoint_override(self):
        CONF.set_override('callback_endpoint_override', 'http://url',
                          group='inspector')
        client = mock.Mock()
        self.assertEqual('http://url/v1/continue',
                         inspector._get_callback_endpoint(client))
        self.assertFalse(client.get_endpoint.called)

    def test_get_callback_endpoint_mdns(self):
        CONF.set_override('callback_endpoint_override', 'mdns',
                          group='inspector')
        client = mock.Mock()
        self.assertEqual('mdns', inspector._get_callback_endpoint(client))
        self.assertFalse(client.get_endpoint.called)

    def test_get_callback_endpoint_no_loopback(self):
        client = mock.Mock()
        client.get_endpoint.return_value = 'http://127.0.0.1:5050'
        self.assertRaisesRegex(exception.InvalidParameterValue, 'Loopback',
                               inspector._get_callback_endpoint, client)


@mock.patch.object(eventlet, 'spawn_n', lambda f, *a, **kw: f(*a, **kw))
@mock.patch('ironic.drivers.modules.inspector._get_client', autospec=True)
class InspectHardwareTestCase(BaseTestCase):
    def test_validate_ok(self, mock_client):
        self.iface.validate(self.task)

    @mock.patch.object(redfish_utils, 'get_system', autospec=True)
    @mock.patch.object(inspect_utils, 'create_ports_if_not_exist',
                       autospec=True)
    def test_validate_require_managed_boot(self, mock_get_system,
                                           mock_create_ports_if_not_exist,
                                           mock_client):
        CONF.set_override('require_managed_boot', True, group='inspector')
        self.driver.boot.validate_inspection.side_effect = (
            exception.UnsupportedDriverExtension(''))
        self.assertRaises(exception.UnsupportedDriverExtension,
                          self.iface.validate, self.task)

    @mock.patch.object(redfish_utils, 'get_system', autospec=True)
    @mock.patch.object(inspect_utils, 'create_ports_if_not_exist',
                       autospec=True)
    def test_unmanaged_ok(self, mock_create_ports_if_not_exist,
                          mock_get_system, mock_client):
        self.driver.boot.validate_inspection.side_effect = (
            exception.UnsupportedDriverExtension(''))
        mock_introspect = mock_client.return_value.start_introspection
        self.assertEqual(states.INSPECTWAIT,
                         self.iface.inspect_hardware(self.task))
        mock_introspect.assert_called_once_with(self.node.uuid)
        self.assertFalse(self.driver.boot.prepare_ramdisk.called)
        self.assertFalse(self.driver.network.add_inspection_network.called)
        self.assertFalse(self.driver.power.reboot.called)
        self.assertFalse(self.driver.network.remove_inspection_network.called)
        self.assertFalse(self.driver.boot.clean_up_ramdisk.called)
        self.assertFalse(self.driver.power.set_power_state.called)

    @mock.patch.object(task_manager, 'acquire', autospec=True)
    @mock.patch.object(redfish_utils, 'get_system', autospec=True)
    @mock.patch.object(inspect_utils, 'create_ports_if_not_exist',
                       autospec=True)
    def test_unmanaged_error(self, mock_create_ports_if_not_exist,
                             mock_get_system, mock_acquire, mock_client):
        mock_acquire.return_value.__enter__.return_value = self.task
        self.driver.boot.validate_inspection.side_effect = (
            exception.UnsupportedDriverExtension(''))
        mock_introspect = mock_client.return_value.start_introspection
        mock_introspect.side_effect = RuntimeError('boom')
        self.iface.inspect_hardware(self.task)
        mock_introspect.assert_called_once_with(self.node.uuid)
        self.assertIn('boom', self.task.node.last_error)
        self.task.process_event.assert_called_once_with('fail')
        self.assertFalse(self.driver.boot.prepare_ramdisk.called)
        self.assertFalse(self.driver.network.add_inspection_network.called)
        self.assertFalse(self.driver.network.remove_inspection_network.called)
        self.assertFalse(self.driver.boot.clean_up_ramdisk.called)
        self.assertFalse(self.driver.power.set_power_state.called)

    @mock.patch.object(redfish_utils, 'get_system', autospec=True)
    @mock.patch.object(inspect_utils, 'create_ports_if_not_exist',
                       autospec=True)
    def test_require_managed_boot(self, mock_create_ports_if_not_exist,
                                  mock_get_system, mock_client):
        CONF.set_override('require_managed_boot', True, group='inspector')
        self.driver.boot.validate_inspection.side_effect = (
            exception.UnsupportedDriverExtension(''))
        mock_introspect = mock_client.return_value.start_introspection
        self.assertRaises(exception.UnsupportedDriverExtension,
                          self.iface.inspect_hardware, self.task)
        self.assertFalse(mock_introspect.called)
        self.assertFalse(self.driver.boot.prepare_ramdisk.called)
        self.assertFalse(self.driver.network.add_inspection_network.called)
        self.assertFalse(self.driver.power.reboot.called)
        self.assertFalse(self.driver.network.remove_inspection_network.called)
        self.assertFalse(self.driver.boot.clean_up_ramdisk.called)
        self.assertFalse(self.driver.power.set_power_state.called)

    @mock.patch.object(redfish_utils, 'get_system', autospec=True)
    @mock.patch.object(inspect_utils, 'create_ports_if_not_exist',
                       autospec=True)
    def test_managed_ok(self, mock_create_ports_if_not_exist,
                        mock_get_system, mock_client):
        endpoint = 'http://192.169.0.42:5050/v1'
        mock_client.return_value.get_endpoint.return_value = endpoint
        mock_introspect = mock_client.return_value.start_introspection
        self.assertEqual(states.INSPECTWAIT,
                         self.iface.inspect_hardware(self.task))
        mock_introspect.assert_called_once_with(self.node.uuid,
                                                manage_boot=False)
        self.driver.boot.prepare_ramdisk.assert_called_once_with(
            self.task, ramdisk_params={
                'ipa-inspection-callback-url': endpoint + '/continue',
            })
        self.driver.network.add_inspection_network.assert_called_once_with(
            self.task)
        self.driver.power.set_power_state.assert_has_calls([
            mock.call(self.task, states.POWER_OFF, timeout=None),
            mock.call(self.task, states.POWER_ON, timeout=None),
        ])
        self.assertFalse(self.driver.network.remove_inspection_network.called)
        self.assertFalse(self.driver.boot.clean_up_ramdisk.called)

    @mock.patch.object(redfish_utils, 'get_system', autospec=True)
    @mock.patch.object(inspect_utils, 'create_ports_if_not_exist',
                       autospec=True)
    def test_managed_custom_params(self, mock_get_system,
                                   mock_create_ports_if_not_exist,
                                   mock_client):
        CONF.set_override('extra_kernel_params',
                          'ipa-inspection-collectors=default,logs '
                          'ipa-collect-dhcp=1 something',
                          group='inspector')
        endpoint = 'http://192.169.0.42:5050/v1'
        mock_client.return_value.get_endpoint.return_value = endpoint
        mock_introspect = mock_client.return_value.start_introspection
        self.iface.validate(self.task)
        self.assertEqual(states.INSPECTWAIT,
                         self.iface.inspect_hardware(self.task))
        mock_introspect.assert_called_once_with(self.node.uuid,
                                                manage_boot=False)
        self.driver.boot.prepare_ramdisk.assert_called_once_with(
            self.task, ramdisk_params={
                'ipa-inspection-callback-url': endpoint + '/continue',
                'ipa-inspection-collectors': 'default,logs',
                'ipa-collect-dhcp': '1',
                'something': None,
            })
        self.driver.network.add_inspection_network.assert_called_once_with(
            self.task)
        self.driver.power.set_power_state.assert_has_calls([
            mock.call(self.task, states.POWER_OFF, timeout=None),
            mock.call(self.task, states.POWER_ON, timeout=None),
        ])
        self.assertFalse(self.driver.network.remove_inspection_network.called)
        self.assertFalse(self.driver.boot.clean_up_ramdisk.called)

    @mock.patch('ironic.drivers.modules.deploy_utils.get_ironic_api_url',
                autospec=True)
    @mock.patch.object(redfish_utils, 'get_system', autospec=True)
    @mock.patch.object(inspect_utils, 'create_ports_if_not_exist',
                       autospec=True)
    def test_managed_fast_track(self, mock_create_ports_if_not_exist,
                                mock_get_system, mock_ironic_url,
                                mock_client):
        CONF.set_override('fast_track', True, group='deploy')
        CONF.set_override('extra_kernel_params',
                          'ipa-inspection-collectors=default,logs '
                          'ipa-collect-dhcp=1',
                          group='inspector')
        endpoint = 'http://192.169.0.42:5050/v1'
        mock_ironic_url.return_value = 'http://192.169.0.42:6385'
        mock_client.return_value.get_endpoint.return_value = endpoint
        mock_introspect = mock_client.return_value.start_introspection
        self.iface.validate(self.task)
        self.assertEqual(states.INSPECTWAIT,
                         self.iface.inspect_hardware(self.task))
        mock_introspect.assert_called_once_with(self.node.uuid,
                                                manage_boot=False)
        self.driver.boot.prepare_ramdisk.assert_called_once_with(
            self.task, ramdisk_params={
                'ipa-inspection-callback-url': endpoint + '/continue',
                'ipa-inspection-collectors': 'default,logs',
                'ipa-collect-dhcp': '1',
                'ipa-api-url': 'http://192.169.0.42:6385',
            })
        self.driver.network.add_inspection_network.assert_called_once_with(
            self.task)
        self.driver.power.set_power_state.assert_has_calls([
            mock.call(self.task, states.POWER_OFF, timeout=None),
            mock.call(self.task, states.POWER_ON, timeout=None),
        ])
        self.assertFalse(self.driver.network.remove_inspection_network.called)
        self.assertFalse(self.driver.boot.clean_up_ramdisk.called)

    @mock.patch('ironic.drivers.modules.deploy_utils.get_ironic_api_url',
                autospec=True)
    @mock.patch.object(redfish_utils, 'get_system', autospec=True)
    @mock.patch.object(inspect_utils, 'create_ports_if_not_exist',
                       autospec=True)
    def test_managed_fast_track_via_driver_info(
            self, mock_create_ports_if_not_exist, mock_get_system,
            mock_ironic_url, mock_client):
        CONF.set_override('extra_kernel_params',
                          'ipa-inspection-collectors=default,logs '
                          'ipa-collect-dhcp=1',
                          group='inspector')
        endpoint = 'http://192.169.0.42:5050/v1'
        mock_ironic_url.return_value = 'http://192.169.0.42:6385'
        mock_client.return_value.get_endpoint.return_value = endpoint
        mock_introspect = mock_client.return_value.start_introspection
        self.task.node.driver_info = {'fast_track': True}
        self.iface.validate(self.task)
        self.assertEqual(states.INSPECTWAIT,
                         self.iface.inspect_hardware(self.task))
        mock_introspect.assert_called_once_with(self.node.uuid,
                                                manage_boot=False)
        self.driver.boot.prepare_ramdisk.assert_called_once_with(
            self.task, ramdisk_params={
                'ipa-inspection-callback-url': endpoint + '/continue',
                'ipa-inspection-collectors': 'default,logs',
                'ipa-collect-dhcp': '1',
                'ipa-api-url': 'http://192.169.0.42:6385',
            })
        self.driver.network.add_inspection_network.assert_called_once_with(
            self.task)
        self.driver.power.set_power_state.assert_has_calls([
            mock.call(self.task, states.POWER_OFF, timeout=None),
            mock.call(self.task, states.POWER_ON, timeout=None),
        ])
        self.assertFalse(self.driver.network.remove_inspection_network.called)
        self.assertFalse(self.driver.boot.clean_up_ramdisk.called)

    @mock.patch.object(task_manager, 'acquire', autospec=True)
    @mock.patch.object(redfish_utils, 'get_system', autospec=True)
    @mock.patch.object(inspect_utils, 'create_ports_if_not_exist',
                       autospec=True)
    def test_managed_error(self, mock_get_system,
                           mock_create_ports_if_not_exist, mock_acquire,
                           mock_client):
        endpoint = 'http://192.169.0.42:5050/v1'
        mock_client.return_value.get_endpoint.return_value = endpoint
        mock_acquire.return_value.__enter__.return_value = self.task
        mock_introspect = mock_client.return_value.start_introspection
        mock_introspect.side_effect = RuntimeError('boom')
        self.assertRaises(exception.HardwareInspectionFailure,
                          self.iface.inspect_hardware, self.task)
        mock_introspect.assert_called_once_with(self.node.uuid,
                                                manage_boot=False)
        self.assertIn('boom', self.task.node.last_error)
        self.driver.boot.prepare_ramdisk.assert_called_once_with(
            self.task, ramdisk_params={
                'ipa-inspection-callback-url': endpoint + '/continue',
            })
        self.driver.network.add_inspection_network.assert_called_once_with(
            self.task)
        self.driver.network.remove_inspection_network.assert_called_once_with(
            self.task)
        self.driver.boot.clean_up_ramdisk.assert_called_once_with(self.task)
        self.driver.power.set_power_state.assert_called_with(
            self.task, 'power off', timeout=None)


@mock.patch('ironic.drivers.modules.inspector._get_client', autospec=True)
class CheckStatusTestCase(BaseTestCase):
    def setUp(self):
        super(CheckStatusTestCase, self).setUp()
        self.node.provision_state = states.INSPECTWAIT

    def test_not_inspecting(self, mock_client):
        mock_get = mock_client.return_value.get_introspection
        self.node.provision_state = states.MANAGEABLE
        inspector._check_status(self.task)
        self.assertFalse(mock_get.called)

    def test_not_check_inspecting(self, mock_client):
        mock_get = mock_client.return_value.get_introspection
        self.node.provision_state = states.INSPECTING
        inspector._check_status(self.task)
        self.assertFalse(mock_get.called)

    def test_not_inspector(self, mock_client):
        mock_get = mock_client.return_value.get_introspection
        self.task.driver.inspect = object()
        inspector._check_status(self.task)
        self.assertFalse(mock_get.called)

    def test_not_finished(self, mock_client):
        mock_get = mock_client.return_value.get_introspection
        mock_get.return_value = mock.Mock(is_finished=False,
                                          error=None,
                                          spec=['is_finished', 'error'])
        inspector._check_status(self.task)
        mock_get.assert_called_once_with(self.node.uuid)
        self.assertFalse(self.task.process_event.called)

    def test_exception_ignored(self, mock_client):
        mock_get = mock_client.return_value.get_introspection
        mock_get.side_effect = RuntimeError('boom')
        inspector._check_status(self.task)
        mock_get.assert_called_once_with(self.node.uuid)
        self.assertFalse(self.task.process_event.called)

    def test_status_ok(self, mock_client):
        mock_get = mock_client.return_value.get_introspection
        mock_get.return_value = mock.Mock(is_finished=True,
                                          error=None,
                                          spec=['is_finished', 'error'])
        inspector._check_status(self.task)
        mock_get.assert_called_once_with(self.node.uuid)
        self.task.process_event.assert_called_once_with('done')
        self.assertFalse(self.driver.network.remove_inspection_network.called)
        self.assertFalse(self.driver.boot.clean_up_ramdisk.called)
        self.assertFalse(self.driver.power.set_power_state.called)

    def test_status_ok_managed(self, mock_client):
        utils.set_node_nested_field(self.node, 'driver_internal_info',
                                    'inspector_manage_boot', True)
        self.node.save()
        mock_get = mock_client.return_value.get_introspection
        mock_get.return_value = mock.Mock(is_finished=True,
                                          error=None,
                                          spec=['is_finished', 'error'])
        inspector._check_status(self.task)
        mock_get.assert_called_once_with(self.node.uuid)
        self.task.process_event.assert_called_once_with('done')
        self.driver.network.remove_inspection_network.assert_called_once_with(
            self.task)
        self.driver.boot.clean_up_ramdisk.assert_called_once_with(self.task)
        self.driver.power.set_power_state.assert_called_once_with(
            self.task, 'power off', timeout=None)

    def test_status_ok_managed_no_power_off(self, mock_client):
        CONF.set_override('power_off', False, group='inspector')
        utils.set_node_nested_field(self.node, 'driver_internal_info',
                                    'inspector_manage_boot', True)
        self.node.save()
        mock_get = mock_client.return_value.get_introspection
        mock_get.return_value = mock.Mock(is_finished=True,
                                          error=None,
                                          spec=['is_finished', 'error'])
        inspector._check_status(self.task)
        mock_get.assert_called_once_with(self.node.uuid)
        self.task.process_event.assert_called_once_with('done')
        self.driver.network.remove_inspection_network.assert_called_once_with(
            self.task)
        self.driver.boot.clean_up_ramdisk.assert_called_once_with(self.task)
        self.assertFalse(self.driver.power.set_power_state.called)

    def test_status_ok_managed_no_power_off_on_fast_track(self, mock_client):
        CONF.set_override('fast_track', True, group='deploy')
        utils.set_node_nested_field(self.node, 'driver_internal_info',
                                    'inspector_manage_boot', True)
        self.node.save()
        mock_get = mock_client.return_value.get_introspection
        mock_get.return_value = mock.Mock(is_finished=True,
                                          error=None,
                                          spec=['is_finished', 'error'])
        inspector._check_status(self.task)
        mock_get.assert_called_once_with(self.node.uuid)
        self.task.process_event.assert_called_once_with('done')
        self.driver.network.remove_inspection_network.assert_called_once_with(
            self.task)
        self.driver.boot.clean_up_ramdisk.assert_called_once_with(self.task)
        self.assertFalse(self.driver.power.set_power_state.called)

    def test_status_error(self, mock_client):
        mock_get = mock_client.return_value.get_introspection
        mock_get.return_value = mock.Mock(is_finished=True,
                                          error='boom',
                                          spec=['is_finished', 'error'])
        inspector._check_status(self.task)
        mock_get.assert_called_once_with(self.node.uuid)
        self.task.process_event.assert_called_once_with('fail')
        self.assertIn('boom', self.node.last_error)
        self.assertFalse(self.driver.network.remove_inspection_network.called)
        self.assertFalse(self.driver.boot.clean_up_ramdisk.called)
        self.assertFalse(self.driver.power.set_power_state.called)

    def test_status_error_managed(self, mock_client):
        utils.set_node_nested_field(self.node, 'driver_internal_info',
                                    'inspector_manage_boot', True)
        self.node.save()
        mock_get = mock_client.return_value.get_introspection
        mock_get.return_value = mock.Mock(is_finished=True,
                                          error='boom',
                                          spec=['is_finished', 'error'])
        inspector._check_status(self.task)
        mock_get.assert_called_once_with(self.node.uuid)
        self.task.process_event.assert_called_once_with('fail')
        self.assertIn('boom', self.node.last_error)
        self.driver.network.remove_inspection_network.assert_called_once_with(
            self.task)
        self.driver.boot.clean_up_ramdisk.assert_called_once_with(self.task)
        self.driver.power.set_power_state.assert_called_once_with(
            self.task, 'power off', timeout=None)

    def test_status_error_managed_no_power_off(self, mock_client):
        CONF.set_override('power_off', False, group='inspector')
        utils.set_node_nested_field(self.node, 'driver_internal_info',
                                    'inspector_manage_boot', True)
        self.node.save()
        mock_get = mock_client.return_value.get_introspection
        mock_get.return_value = mock.Mock(is_finished=True,
                                          error='boom',
                                          spec=['is_finished', 'error'])
        inspector._check_status(self.task)
        mock_get.assert_called_once_with(self.node.uuid)
        self.task.process_event.assert_called_once_with('fail')
        self.assertIn('boom', self.node.last_error)
        self.driver.network.remove_inspection_network.assert_called_once_with(
            self.task)
        self.driver.boot.clean_up_ramdisk.assert_called_once_with(self.task)
        self.assertFalse(self.driver.power.set_power_state.called)

    def _test_status_clean_up_failed(self, mock_client):
        utils.set_node_nested_field(self.node, 'driver_internal_info',
                                    'inspector_manage_boot', True)
        self.node.save()
        mock_get = mock_client.return_value.get_introspection
        mock_get.return_value = mock.Mock(is_finished=True,
                                          error=None,
                                          spec=['is_finished', 'error'])
        inspector._check_status(self.task)
        mock_get.assert_called_once_with(self.node.uuid)
        self.task.process_event.assert_called_once_with('fail')
        self.assertIn('boom', self.node.last_error)

    def test_status_boot_clean_up_failed(self, mock_client):
        self.driver.boot.clean_up_ramdisk.side_effect = RuntimeError('boom')

        self._test_status_clean_up_failed(mock_client)

        self.driver.boot.clean_up_ramdisk.assert_called_once_with(self.task)

    def test_status_network_clean_up_failed(self, mock_client):
        self.driver.network.remove_inspection_network.side_effect = \
            RuntimeError('boom')

        self._test_status_clean_up_failed(mock_client)

        self.driver.network.remove_inspection_network.assert_called_once_with(
            self.task)
        self.driver.boot.clean_up_ramdisk.assert_called_once_with(self.task)

    @mock.patch.object(inspect_utils, 'store_introspection_data',
                       autospec=True)
    def test_status_ok_store_inventory(self, mock_store_data, mock_client):
        mock_get = mock_client.return_value.get_introspection
        mock_get.return_value = mock.Mock(is_finished=True,
                                          error=None,
                                          spec=['is_finished', 'error'])
        fake_introspection_data = {
            "inventory": {"cpu": "amd"}, "disks": [{"name": "/dev/vda"}]}
        mock_get_data = mock_client.return_value.get_introspection_data
        mock_get_data.return_value = fake_introspection_data
        inspector._check_status(self.task)
        mock_get.assert_called_once_with(self.node.uuid)
        mock_get_data.assert_called_once_with(self.node.uuid, processed=True)
        mock_store_data.assert_called_once_with(self.node,
                                                fake_introspection_data,
                                                self.task.context)

    def test_status_ok_store_inventory_nostore(self, mock_client):
        CONF.set_override('data_backend', 'none', group='inventory')
        mock_get = mock_client.return_value.get_introspection
        mock_get.return_value = mock.Mock(is_finished=True,
                                          error=None,
                                          spec=['is_finished', 'error'])
        mock_get_data = mock_client.return_value.get_introspection_data
        inspector._check_status(self.task)
        mock_get.assert_called_once_with(self.node.uuid)
        mock_get_data.assert_not_called()

    def test_status_error_dont_store_inventory(self, mock_client):
        CONF.set_override('data_backend', 'database',
                          group='inventory')
        mock_get = mock_client.return_value.get_introspection
        mock_get.return_value = mock.Mock(is_finished=True,
                                          error='boom',
                                          spec=['is_finished', 'error'])
        mock_get_data = mock_client.return_value.get_introspection_data
        inspector._check_status(self.task)
        mock_get.assert_called_once_with(self.node.uuid)
        mock_get_data.assert_not_called()


@mock.patch('ironic.drivers.modules.inspector._get_client', autospec=True)
class InspectHardwareAbortTestCase(BaseTestCase):
    def test_abort_ok(self, mock_client):
        mock_abort = mock_client.return_value.abort_introspection
        self.iface.abort(self.task)
        mock_abort.assert_called_once_with(self.node.uuid)

    def test_abort_error(self, mock_client):
        mock_abort = mock_client.return_value.abort_introspection
        mock_abort.side_effect = RuntimeError('boom')
        self.assertRaises(RuntimeError, self.iface.abort, self.task)

        mock_abort.assert_called_once_with(self.node.uuid)
