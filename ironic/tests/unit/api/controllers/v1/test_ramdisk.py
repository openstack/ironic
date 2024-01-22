# Copyright 2016 Red Hat, Inc.
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
"""
Tests for the API /lookup/ methods.
"""

from http import client as http_client
from unittest import mock

import fixtures
from keystonemiddleware import auth_token
from oslo_config import cfg
from oslo_utils import uuidutils

from ironic.api.controllers import base as api_base
from ironic.api.controllers import v1 as api_v1
from ironic.api.controllers.v1 import ramdisk
from ironic.common import exception
from ironic.common import states
from ironic.conductor import rpcapi
from ironic.drivers.modules import inspect_utils
from ironic.tests.unit.api import base as test_api_base
from ironic.tests.unit.objects import utils as obj_utils


CONF = cfg.CONF


class TestLookup(test_api_base.BaseApiTest):
    addresses = ['11:22:33:44:55:66', '66:55:44:33:22:11']

    def setUp(self):
        super(TestLookup, self).setUp()
        self.node = obj_utils.create_test_node(self.context,
                                               uuid=uuidutils.generate_uuid(),
                                               provision_state='deploying')
        self.node2 = obj_utils.create_test_node(self.context,
                                                uuid=uuidutils.generate_uuid(),
                                                provision_state='available')
        CONF.set_override('agent_backend', 'statsd', 'metrics')
        self.mock_get_conductor_for = self.useFixture(
            fixtures.MockPatchObject(rpcapi.ConductorAPI, 'get_conductor_for',
                                     autospec=True)).mock
        self.mock_get_conductor_for.return_value = 'fake.conductor'
        self.mock_get_node_with_token = self.useFixture(
            fixtures.MockPatchObject(rpcapi.ConductorAPI,
                                     'get_node_with_token',
                                     autospec=True)).mock

    def _set_secret_mock(self, node, token_value):
        driver_internal = node.driver_internal_info
        driver_internal['agent_secret_token'] = token_value
        node.driver_internal_info = driver_internal
        self.mock_get_node_with_token.return_value = node

    def _check_config(self, data):
        expected_config = {
            'metrics': {
                'backend': 'statsd',
                'prepend_host': CONF.metrics.agent_prepend_host,
                'prepend_uuid': CONF.metrics.agent_prepend_uuid,
                'prepend_host_reverse':
                    CONF.metrics.agent_prepend_host_reverse,
                'global_prefix': CONF.metrics.agent_global_prefix
            },
            'metrics_statsd': {
                'statsd_host': CONF.metrics_statsd.agent_statsd_host,
                'statsd_port': CONF.metrics_statsd.agent_statsd_port
            },
            'heartbeat_timeout': CONF.api.ramdisk_heartbeat_timeout,
            'agent_token': mock.ANY,
            'agent_token_required': True,
            'agent_md5_checksum_enable': CONF.agent.allow_md5_checksum,
        }
        self.assertEqual(expected_config, data['config'])
        self.assertIsNotNone(data['config']['agent_token'])
        self.assertNotEqual('******', data['config']['agent_token'])

    def test_nothing_provided(self):
        response = self.get_json(
            '/lookup',
            headers={api_base.Version.string: str(api_v1.max_version())},
            expect_errors=True)
        self.assertEqual(http_client.BAD_REQUEST, response.status_int)

    def test_not_found(self):
        response = self.get_json(
            '/lookup?addresses=%s' % ','.join(self.addresses),
            headers={api_base.Version.string: str(api_v1.max_version())},
            expect_errors=True)
        self.assertEqual(http_client.NOT_FOUND, response.status_int)

    def test_old_api_version(self):
        obj_utils.create_test_port(self.context,
                                   node_id=self.node.id,
                                   address=self.addresses[1])

        response = self.get_json(
            '/lookup?addresses=%s' % ','.join(self.addresses),
            headers={api_base.Version.string: str(api_v1.min_version())},
            expect_errors=True)
        self.assertEqual(http_client.NOT_FOUND, response.status_int)

    def test_found_by_addresses(self):
        self._set_secret_mock(self.node, 'some-value')
        obj_utils.create_test_port(self.context,
                                   node_id=self.node.id,
                                   address=self.addresses[1])

        data = self.get_json(
            '/lookup?addresses=%s' % ','.join(self.addresses),
            headers={api_base.Version.string: str(api_v1.max_version())})
        self.assertEqual(self.node.uuid, data['node']['uuid'])
        self.assertEqual(set(ramdisk._LOOKUP_RETURN_FIELDS) | {'links'},
                         set(data['node']))
        self._check_config(data)

    @mock.patch.object(ramdisk.LOG, 'warning', autospec=True)
    def test_ignore_malformed_address(self, mock_log):
        self._set_secret_mock(self.node, '123456')
        obj_utils.create_test_port(self.context,
                                   node_id=self.node.id,
                                   address=self.addresses[1])

        addresses = ('not-a-valid-address,80:00:02:48:fe:80:00:00:00:00:00:00'
                     ':f4:52:14:03:00:54:06:c2,' + ','.join(self.addresses))
        data = self.get_json(
            '/lookup?addresses=%s' % addresses,
            headers={api_base.Version.string: str(api_v1.max_version())})
        self.assertEqual(self.node.uuid, data['node']['uuid'])
        self.assertEqual(set(ramdisk._LOOKUP_RETURN_FIELDS) | {'links'},
                         set(data['node']))
        self._check_config(data)
        self.assertTrue(mock_log.called)

    def test_found_by_uuid(self):
        self._set_secret_mock(self.node, 'this_thing_on?')
        data = self.get_json(
            '/lookup?addresses=%s&node_uuid=%s' %
            (','.join(self.addresses), self.node.uuid),
            headers={api_base.Version.string: str(api_v1.max_version())})
        self.assertEqual(self.node.uuid, data['node']['uuid'])
        self.assertEqual(set(ramdisk._LOOKUP_RETURN_FIELDS) | {'links'},
                         set(data['node']))
        self._check_config(data)

    def test_found_by_only_uuid(self):
        self._set_secret_mock(self.node, 'xyzabc')
        data = self.get_json(
            '/lookup?node_uuid=%s' % self.node.uuid,
            headers={api_base.Version.string: str(api_v1.max_version())})
        self.assertEqual(self.node.uuid, data['node']['uuid'])
        self.assertEqual(set(ramdisk._LOOKUP_RETURN_FIELDS) | {'links'},
                         set(data['node']))
        self._check_config(data)

    def test_restrict_lookup(self):
        response = self.get_json(
            '/lookup?addresses=%s&node_uuid=%s' %
            (','.join(self.addresses), self.node2.uuid),
            headers={api_base.Version.string: str(api_v1.max_version())},
            expect_errors=True)
        self.assertEqual(http_client.NOT_FOUND, response.status_int)

    def test_no_restrict_lookup(self):
        CONF.set_override('restrict_lookup', False, 'api')
        self._set_secret_mock(self.node2, '234567890')
        data = self.get_json(
            '/lookup?addresses=%s&node_uuid=%s' %
            (','.join(self.addresses), self.node2.uuid),
            headers={api_base.Version.string: str(api_v1.max_version())})
        self.assertEqual(self.node2.uuid, data['node']['uuid'])
        self.assertEqual(set(ramdisk._LOOKUP_RETURN_FIELDS) | {'links'},
                         set(data['node']))
        self._check_config(data)

    def test_fast_deploy_lookup(self):
        self._set_secret_mock(self.node, 'abcxyz')
        CONF.set_override('fast_track', True, 'deploy')
        for provision_state in [states.ENROLL, states.MANAGEABLE,
                                states.AVAILABLE]:
            self.node.provision_state = provision_state
            data = self.get_json(
                '/lookup?addresses=%s&node_uuid=%s' %
                (','.join(self.addresses), self.node.uuid),
                headers={api_base.Version.string: str(api_v1.max_version())})
            self.assertEqual(self.node.uuid, data['node']['uuid'])


@mock.patch.object(rpcapi.ConductorAPI, 'get_topic_for',
                   lambda *n: 'test-topic')
class TestHeartbeat(test_api_base.BaseApiTest):
    def test_old_api_version(self):
        response = self.post_json(
            '/heartbeat/%s' % uuidutils.generate_uuid(),
            {'callback_url': 'url'},
            headers={api_base.Version.string: str(api_v1.min_version())},
            expect_errors=True)
        self.assertEqual(http_client.NOT_FOUND, response.status_int)

    def test_node_not_found(self):
        response = self.post_json(
            '/heartbeat/%s' % uuidutils.generate_uuid(),
            {'callback_url': 'url'},
            headers={api_base.Version.string: str(api_v1.max_version())},
            expect_errors=True)
        self.assertEqual(http_client.NOT_FOUND, response.status_int)

    @mock.patch.object(rpcapi.ConductorAPI, 'heartbeat', autospec=True)
    def test_ok(self, mock_heartbeat):
        node = obj_utils.create_test_node(self.context)
        response = self.post_json(
            '/heartbeat/%s' % node.uuid,
            {'callback_url': 'url',
             'agent_token': 'x'},
            headers={api_base.Version.string: str(api_v1.max_version())})
        self.assertEqual(http_client.ACCEPTED, response.status_int)
        self.assertEqual(b'', response.body)
        mock_heartbeat.assert_called_once_with(mock.ANY, mock.ANY,
                                               node.uuid, 'url', None, 'x',
                                               None, None, None,
                                               topic='test-topic')

    @mock.patch.object(rpcapi.ConductorAPI, 'heartbeat', autospec=True)
    def test_ok_with_json(self, mock_heartbeat):
        node = obj_utils.create_test_node(self.context)
        response = self.post_json(
            '/heartbeat/%s.json' % node.uuid,
            {'callback_url': 'url',
             'agent_token': 'maybe some magic'},
            headers={api_base.Version.string: str(api_v1.max_version())})
        self.assertEqual(http_client.ACCEPTED, response.status_int)
        self.assertEqual(b'', response.body)
        mock_heartbeat.assert_called_once_with(mock.ANY, mock.ANY,
                                               node.uuid, 'url', None,
                                               'maybe some magic',
                                               None, None, None,
                                               topic='test-topic')

    @mock.patch.object(rpcapi.ConductorAPI, 'heartbeat', autospec=True)
    def test_ok_by_name(self, mock_heartbeat):
        node = obj_utils.create_test_node(self.context, name='test.1')
        response = self.post_json(
            '/heartbeat/%s' % node.name,
            {'callback_url': 'url',
             'agent_token': 'token'},
            headers={api_base.Version.string: str(api_v1.max_version())})
        self.assertEqual(http_client.ACCEPTED, response.status_int)
        self.assertEqual(b'', response.body)
        mock_heartbeat.assert_called_once_with(mock.ANY, mock.ANY,
                                               node.uuid, 'url', None,
                                               'token', None, None, None,
                                               topic='test-topic')

    @mock.patch.object(rpcapi.ConductorAPI, 'heartbeat', autospec=True)
    def test_ok_agent_version(self, mock_heartbeat):
        node = obj_utils.create_test_node(self.context)
        response = self.post_json(
            '/heartbeat/%s' % node.uuid,
            {'callback_url': 'url',
             'agent_version': '1.4.1',
             'agent_token': 'meow'},
            headers={api_base.Version.string: str(api_v1.max_version())})
        self.assertEqual(http_client.ACCEPTED, response.status_int)
        self.assertEqual(b'', response.body)
        mock_heartbeat.assert_called_once_with(mock.ANY, mock.ANY,
                                               node.uuid, 'url', '1.4.1',
                                               'meow',
                                               None, None, None,
                                               topic='test-topic')

    @mock.patch.object(rpcapi.ConductorAPI, 'heartbeat', autospec=True)
    def test_old_API_agent_version_error(self, mock_heartbeat):
        node = obj_utils.create_test_node(self.context)
        response = self.post_json(
            '/heartbeat/%s' % node.uuid,
            {'callback_url': 'url',
             'agent_version': '1.4.1'},
            headers={api_base.Version.string: '1.35'},
            expect_errors=True)
        self.assertEqual(http_client.BAD_REQUEST, response.status_int)

    @mock.patch.object(rpcapi.ConductorAPI, 'heartbeat', autospec=True)
    def test_heartbeat_rejects_different_callback_url(self, mock_heartbeat):
        node = obj_utils.create_test_node(
            self.context,
            driver_internal_info={'agent_url': 'url'})
        response = self.post_json(
            '/heartbeat/%s' % node.uuid,
            {'callback_url': 'url2'},
            headers={api_base.Version.string: str(api_v1.max_version())},
            expect_errors=True)
        self.assertEqual(http_client.BAD_REQUEST, response.status_int)

    @mock.patch.object(rpcapi.ConductorAPI, 'heartbeat', autospec=True)
    def test_ok_agent_token(self, mock_heartbeat):
        node = obj_utils.create_test_node(self.context)
        response = self.post_json(
            '/heartbeat/%s' % node.uuid,
            {'callback_url': 'url',
             'agent_token': 'abcdef1'},
            headers={api_base.Version.string: str(api_v1.max_version())})
        self.assertEqual(http_client.ACCEPTED, response.status_int)
        self.assertEqual(b'', response.body)
        mock_heartbeat.assert_called_once_with(mock.ANY, mock.ANY,
                                               node.uuid, 'url', None,
                                               'abcdef1', None, None, None,
                                               topic='test-topic')

    @mock.patch.object(rpcapi.ConductorAPI, 'heartbeat', autospec=True)
    def test_ok_agent_verify_ca(self, mock_heartbeat):
        node = obj_utils.create_test_node(self.context)
        response = self.post_json(
            '/heartbeat/%s' % node.uuid,
            {'callback_url': 'url',
             'agent_token': 'meow',
             'agent_verify_ca': 'abcdef1'},
            headers={api_base.Version.string: str(api_v1.max_version())})
        self.assertEqual(http_client.ACCEPTED, response.status_int)
        self.assertEqual(b'', response.body)
        mock_heartbeat.assert_called_once_with(mock.ANY, mock.ANY,
                                               node.uuid, 'url', None,
                                               'meow', 'abcdef1', None, None,
                                               topic='test-topic')

    @mock.patch.object(rpcapi.ConductorAPI, 'heartbeat', autospec=True)
    def test_ok_agent_status_and_status(self, mock_heartbeat):
        node = obj_utils.create_test_node(self.context)
        response = self.post_json(
            '/heartbeat/%s' % node.uuid,
            {'callback_url': 'url',
             'agent_token': 'meow',
             'agent_status': 'start',
             'agent_status_message': 'woof',
             'agent_verify_ca': 'abcdef1'},
            headers={api_base.Version.string: str(api_v1.max_version())})
        self.assertEqual(http_client.ACCEPTED, response.status_int)
        self.assertEqual(b'', response.body)
        mock_heartbeat.assert_called_once_with(mock.ANY, mock.ANY,
                                               node.uuid, 'url', None,
                                               'meow', 'abcdef1', 'start',
                                               'woof', topic='test-topic')

    @mock.patch.object(rpcapi.ConductorAPI, 'heartbeat', autospec=True)
    def test_bad_invalid_agent_status(self, mock_heartbeat):
        node = obj_utils.create_test_node(self.context)
        response = self.post_json(
            '/heartbeat/%s' % node.uuid,
            {'callback_url': 'url',
             'agent_token': 'meow',
             'agent_status': 'invalid_state',
             'agent_status_message': 'woof',
             'agent_verify_ca': 'abcdef1'},
            headers={api_base.Version.string: str(api_v1.max_version())},
            expect_errors=True)
        self.assertEqual(http_client.BAD_REQUEST, response.status_int)

    @mock.patch.object(rpcapi.ConductorAPI, 'heartbeat', autospec=True)
    def test_old_API_agent_verify_ca_error(self, mock_heartbeat):
        node = obj_utils.create_test_node(self.context)
        response = self.post_json(
            '/heartbeat/%s' % node.uuid,
            {'callback_url': 'url',
             'agent_token': 'meow',
             'agent_verify_ca': 'abcd'},
            headers={api_base.Version.string: '1.67'},
            expect_errors=True)
        self.assertEqual(http_client.BAD_REQUEST, response.status_int)

    @mock.patch.object(rpcapi.ConductorAPI, 'heartbeat', autospec=True)
    def test_old_api_agent_status_error(self, mock_heartbeat):
        node = obj_utils.create_test_node(self.context)
        response = self.post_json(
            '/heartbeat/%s' % node.uuid,
            {'callback_url': 'url',
             'agent_token': 'meow',
             'agent_verify_ca': 'abcd',
             'agent_status': 'wow',
             'agent_status_message': 'much status'},
            headers={api_base.Version.string: '1.71'},
            expect_errors=True)
        self.assertEqual(http_client.BAD_REQUEST, response.status_int)


@mock.patch.object(auth_token.AuthProtocol, 'process_request',
                   lambda *_: None)
class TestLookupScopedRBAC(TestLookup):

    """Test class to execute the Lookup tests with RBAC enforcement."""
    def setUp(self):
        super(TestLookupScopedRBAC, self).setUp()

        cfg.CONF.set_override('enforce_scope', True, group='oslo_policy')
        cfg.CONF.set_override('enforce_new_defaults', True,
                              group='oslo_policy')
        cfg.CONF.set_override('auth_strategy', 'keystone')


@mock.patch.object(auth_token.AuthProtocol, 'process_request',
                   lambda *_: None)
class TestHeartbeatScopedRBAC(TestHeartbeat):

    """Test class to execute the Heartbeat tests with RBAC enforcement."""
    def setUp(self):
        super(TestHeartbeatScopedRBAC, self).setUp()

        cfg.CONF.set_override('enforce_scope', True, group='oslo_policy')
        cfg.CONF.set_override('enforce_new_defaults', True,
                              group='oslo_policy')
        cfg.CONF.set_override('auth_strategy', 'keystone')


@mock.patch.object(rpcapi.ConductorAPI, 'get_topic_for',
                   lambda *n: 'test-topic')
@mock.patch.object(rpcapi.ConductorAPI, 'continue_inspection', autospec=True)
@mock.patch.object(inspect_utils, 'lookup_node', autospec=True)
class TestContinueInspection(test_api_base.BaseApiTest):

    def setUp(self):
        super().setUp()
        self.addresses = ['11:22:33:44:55:66', '66:55:44:33:22:11']
        self.bmcs = ['192.0.2.42', '2001:db8::42']
        self.inventory = {
            'bmc_address': self.bmcs[0],
            'bmc_v6address': self.bmcs[1],
            'interfaces': [
                {'mac_address': mac, 'name': f'em{i}'}
                for i, mac in enumerate(self.addresses)
            ],
        }
        self.data = {
            'inventory': self.inventory,
            'test': 42,
        }
        self.node = obj_utils.create_test_node(self.context,
                                               uuid=uuidutils.generate_uuid(),
                                               provision_state='inspect wait')

    def test_inspector_compatibility(self, mock_lookup, mock_continue):
        mock_lookup.return_value = self.node
        response = self.post_json('/continue_inspection', self.data)
        self.assertEqual(http_client.ACCEPTED, response.status_int)
        self.assertEqual({'uuid': self.node.uuid}, response.json)
        mock_lookup.assert_called_once_with(
            mock.ANY, self.addresses, self.bmcs, node_uuid=None)
        mock_continue.assert_called_once_with(
            mock.ANY, mock.ANY, self.node.uuid, inventory=self.inventory,
            plugin_data={'test': 42}, topic='test-topic')

    @mock.patch.object(rpcapi.ConductorAPI, 'get_node_with_token',
                       autospec=True)
    def test_new_api(self, mock_get_node, mock_lookup, mock_continue):
        mock_lookup.return_value = self.node
        mock_get_node.return_value = self.node
        response = self.post_json(
            '/continue_inspection', self.data,
            headers={api_base.Version.string: str(api_v1.max_version())})
        self.assertEqual(http_client.ACCEPTED, response.status_int)
        self.assertEqual(self.node.uuid, response.json['node']['uuid'])
        self.assertEqual(set(ramdisk._LOOKUP_RETURN_FIELDS) | {'links'},
                         set(response.json['node']))
        mock_lookup.assert_called_once_with(
            mock.ANY, self.addresses, self.bmcs, node_uuid=None)
        mock_continue.assert_called_once_with(
            mock.ANY, mock.ANY, self.node.uuid, inventory=self.inventory,
            plugin_data={'test': 42}, topic='test-topic')
        mock_get_node.assert_called_once_with(
            mock.ANY, mock.ANY, self.node.uuid, topic='test-topic')

    def test_old_api_version(self, mock_lookup, mock_continue):
        response = self.post_json(
            '/continue_inspection', self.data,
            headers={api_base.Version.string: '1.83'},
            expect_errors=True)
        self.assertEqual(http_client.NOT_FOUND, response.status_int)
        self.assertIn("API version", response.text)
        mock_lookup.assert_not_called()
        mock_continue.assert_not_called()

    def test_invalid_schema(self, mock_lookup, mock_continue):
        del self.data['inventory']['interfaces']
        response = self.post_json(
            '/continue_inspection', self.data,
            headers={api_base.Version.string: str(api_v1.max_version())},
            expect_errors=True)
        self.assertEqual(http_client.BAD_REQUEST, response.status_int)
        # JSON schema errors can change between versions, so only make sure
        # it mentions the required field.
        self.assertIn("interfaces", response.text)
        mock_lookup.assert_not_called()
        mock_continue.assert_not_called()

    def test_no_usable_lookup_data(self, mock_lookup, mock_continue):
        self.data['inventory']['interfaces'] = [{'mac_address': 'meow'}]
        del self.data['inventory']['bmc_address']
        del self.data['inventory']['bmc_v6address']
        response = self.post_json(
            '/continue_inspection', self.data,
            headers={api_base.Version.string: str(api_v1.max_version())},
            expect_errors=True)
        self.assertEqual(http_client.BAD_REQUEST, response.status_int)
        self.assertIn("No lookup information", response.text)
        mock_lookup.assert_not_called()
        mock_continue.assert_not_called()


@mock.patch.object(auth_token.AuthProtocol, 'process_request',
                   lambda *_: None)
class TestContinueInspectionScopedRBAC(TestContinueInspection):

    def setUp(self):
        super().setUp()

        cfg.CONF.set_override('enforce_scope', True, group='oslo_policy')
        cfg.CONF.set_override('enforce_new_defaults', True,
                              group='oslo_policy')
        cfg.CONF.set_override('auth_strategy', 'keystone')


@mock.patch.object(rpcapi.ConductorAPI, 'get_topic_for', autospec=True,
                   return_value='test-topic')
@mock.patch.object(rpcapi.ConductorAPI, 'create_node', autospec=True)
@mock.patch.object(rpcapi.ConductorAPI, 'continue_inspection', autospec=True)
@mock.patch.object(inspect_utils, 'lookup_node', autospec=True,
                   side_effect=inspect_utils.AutoEnrollPossible)
class TestContinueInspectionAutoDiscovery(test_api_base.BaseApiTest):

    def setUp(self):
        super().setUp()
        CONF.set_override('enabled', True, group='auto_discovery')
        CONF.set_override('driver', 'fake-hardware', group='auto_discovery')
        self.addresses = ['11:22:33:44:55:66', '66:55:44:33:22:11']
        self.bmcs = ['192.0.2.42']
        self.inventory = {
            'bmc_address': self.bmcs[0],
            'interfaces': [
                {'mac_address': mac, 'name': f'em{i}'}
                for i, mac in enumerate(self.addresses)
            ],
        }
        self.data = {
            'inventory': self.inventory,
            'test': 42,
        }
        self.node = obj_utils.get_test_node(self.context,
                                            uuid=uuidutils.generate_uuid(),
                                            provision_state='enroll')

    def test_enroll(self, mock_lookup, mock_continue, mock_create,
                    mock_get_topic):
        mock_create.return_value = self.node
        response = self.post_json('/continue_inspection', self.data)
        self.assertEqual(http_client.ACCEPTED, response.status_int)
        self.assertEqual({'uuid': self.node.uuid}, response.json)
        mock_lookup.assert_called_once_with(
            mock.ANY, self.addresses, self.bmcs, node_uuid=None)
        mock_continue.assert_called_once_with(
            mock.ANY, mock.ANY, self.node.uuid, inventory=self.inventory,
            plugin_data={'test': 42, 'auto_discovered': True},
            topic='test-topic')
        new_node = mock_create.call_args.args[2]  # create(self, context, node)
        self.assertEqual('fake-hardware', new_node.driver)
        self.assertIsNone(new_node.resource_class)
        self.assertEqual('', new_node.conductor_group)
        self.assertEqual('enroll', new_node.provision_state)

    def test_wrong_driver(self, mock_lookup, mock_continue, mock_create,
                          mock_get_topic):
        mock_get_topic.side_effect = exception.NoValidHost()
        response = self.post_json(
            '/continue_inspection', self.data,
            expect_errors=True)
        self.assertEqual(http_client.INTERNAL_SERVER_ERROR,
                         response.status_int)
        mock_lookup.assert_called_once_with(
            mock.ANY, self.addresses, self.bmcs, node_uuid=None)
        mock_create.assert_not_called()
        mock_continue.assert_not_called()

    def test_override_defaults(self, mock_lookup, mock_continue, mock_create,
                               mock_get_topic):
        CONF.set_override('default_resource_class', 'xlarge-1')
        # TODO(dtantsur): default_conductor_group
        mock_create.return_value = self.node
        response = self.post_json('/continue_inspection', self.data)
        self.assertEqual(http_client.ACCEPTED, response.status_int)
        mock_lookup.assert_called_once_with(
            mock.ANY, self.addresses, self.bmcs, node_uuid=None)
        mock_continue.assert_called_once_with(
            mock.ANY, mock.ANY, self.node.uuid, inventory=self.inventory,
            plugin_data={'test': 42, 'auto_discovered': True},
            topic='test-topic')
        new_node = mock_create.call_args.args[2]  # create(self, context, node)
        self.assertEqual('fake-hardware', new_node.driver)
        self.assertEqual('xlarge-1', new_node.resource_class)
        self.assertEqual('', new_node.conductor_group)
