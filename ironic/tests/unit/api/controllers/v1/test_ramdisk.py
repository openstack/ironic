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

import fixtures
import mock
from oslo_config import cfg
from oslo_utils import uuidutils

from ironic.api.controllers import base as api_base
from ironic.api.controllers import v1 as api_v1
from ironic.api.controllers.v1 import ramdisk
from ironic.common import states
from ironic.conductor import rpcapi
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
        expected_metrics = {
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
            'agent_token': mock.ANY
        }
        self.assertEqual(expected_metrics, data['config'])
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
            {'callback_url': 'url'},
            headers={api_base.Version.string: str(api_v1.max_version())})
        self.assertEqual(http_client.ACCEPTED, response.status_int)
        self.assertEqual(b'', response.body)
        mock_heartbeat.assert_called_once_with(mock.ANY, mock.ANY,
                                               node.uuid, 'url', None, None,
                                               topic='test-topic')

    @mock.patch.object(rpcapi.ConductorAPI, 'heartbeat', autospec=True)
    def test_ok_with_json(self, mock_heartbeat):
        node = obj_utils.create_test_node(self.context)
        response = self.post_json(
            '/heartbeat/%s.json' % node.uuid,
            {'callback_url': 'url'},
            headers={api_base.Version.string: str(api_v1.max_version())})
        self.assertEqual(http_client.ACCEPTED, response.status_int)
        self.assertEqual(b'', response.body)
        mock_heartbeat.assert_called_once_with(mock.ANY, mock.ANY,
                                               node.uuid, 'url', None, None,
                                               topic='test-topic')

    @mock.patch.object(rpcapi.ConductorAPI, 'heartbeat', autospec=True)
    def test_ok_by_name(self, mock_heartbeat):
        node = obj_utils.create_test_node(self.context, name='test.1')
        response = self.post_json(
            '/heartbeat/%s' % node.name,
            {'callback_url': 'url'},
            headers={api_base.Version.string: str(api_v1.max_version())})
        self.assertEqual(http_client.ACCEPTED, response.status_int)
        self.assertEqual(b'', response.body)
        mock_heartbeat.assert_called_once_with(mock.ANY, mock.ANY,
                                               node.uuid, 'url', None, None,
                                               topic='test-topic')

    @mock.patch.object(rpcapi.ConductorAPI, 'heartbeat', autospec=True)
    def test_ok_agent_version(self, mock_heartbeat):
        node = obj_utils.create_test_node(self.context)
        response = self.post_json(
            '/heartbeat/%s' % node.uuid,
            {'callback_url': 'url',
             'agent_version': '1.4.1'},
            headers={api_base.Version.string: str(api_v1.max_version())})
        self.assertEqual(http_client.ACCEPTED, response.status_int)
        self.assertEqual(b'', response.body)
        mock_heartbeat.assert_called_once_with(mock.ANY, mock.ANY,
                                               node.uuid, 'url', '1.4.1', None,
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
                                               'abcdef1',
                                               topic='test-topic')
