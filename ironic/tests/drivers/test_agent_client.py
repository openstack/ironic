# Copyright 2014 Rackspace, Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import json

import mock
import requests

from ironic.common import exception
from ironic.drivers.modules import agent_client
from ironic.tests import base


class MockResponse(object):
    def __init__(self, data):
        self.data = data
        self.text = json.dumps(data)

    def json(self):
        return self.data


class MockNode(object):
    def __init__(self):
        self.uuid = 'uuid'
        self.driver_info = {
            'agent_url': "http://127.0.0.1:9999"
        }
        self.instance_info = {}


class TestAgentClient(base.TestCase):
    def setUp(self):
        super(TestAgentClient, self).setUp()
        self.client = agent_client.AgentClient()
        self.client.session = mock.Mock(autospec=requests.Session)
        self.node = MockNode()

    def test__get_command_url(self):
        command_url = self.client._get_command_url(self.node)
        expected = self.node.driver_info['agent_url'] + '/v1/commands'
        self.assertEqual(expected, command_url)

    def test__get_command_url_fail(self):
        del self.node.driver_info['agent_url']
        self.assertRaises(exception.IronicException,
                          self.client._get_command_url,
                          self.node)

    def test__get_command_body(self):
        expected = json.dumps({'name': 'prepare_image', 'params': {}})
        self.assertEqual(expected,
                         self.client._get_command_body('prepare_image', {}))

    def test__command(self):
        response_data = {'status': 'ok'}
        self.client.session.post.return_value = MockResponse(response_data)
        method = 'standby.run_image'
        image_info = {'image_id': 'test_image'}
        params = {'image_info': image_info}

        url = self.client._get_command_url(self.node)
        body = self.client._get_command_body(method, params)
        headers = {'Content-Type': 'application/json'}

        response = self.client._command(self.node, method, params)
        self.assertEqual(response, response_data)
        self.client.session.post.assert_called_once_with(
            url,
            data=body,
            headers=headers,
            params={'wait': 'false'})

    def test_get_commands_status(self):
        with mock.patch.object(self.client.session, 'get') as mock_get:
            res = mock.Mock()
            res.json.return_value = {'commands': []}
            mock_get.return_value = res
            self.assertEqual([], self.client.get_commands_status(self.node))

    def test_deploy_is_done(self):
        with mock.patch.object(self.client, 'get_commands_status') as mock_s:
            mock_s.return_value = [{
                'command_name': 'prepare_image',
                'command_status': 'SUCCESS'
            }]
            self.assertTrue(self.client.deploy_is_done(self.node))

    def test_deploy_is_done_empty_response(self):
        with mock.patch.object(self.client, 'get_commands_status') as mock_s:
            mock_s.return_value = []
            self.assertFalse(self.client.deploy_is_done(self.node))

    def test_deploy_is_done_race(self):
        with mock.patch.object(self.client, 'get_commands_status') as mock_s:
            mock_s.return_value = [{
                'command_name': 'some_other_command',
                'command_status': 'SUCCESS'
            }]
            self.assertFalse(self.client.deploy_is_done(self.node))

    def test_deploy_is_done_still_running(self):
        with mock.patch.object(self.client, 'get_commands_status') as mock_s:
            mock_s.return_value = [{
                'command_name': 'prepare_image',
                'command_status': 'RUNNING'
            }]
            self.assertFalse(self.client.deploy_is_done(self.node))

    @mock.patch('uuid.uuid4', mock.MagicMock(return_value='uuid'))
    def test_prepare_image(self):
        self.client._command = mock.Mock()
        image_info = {'image_id': 'image'}
        params = {'image_info': image_info}

        self.client.prepare_image(self.node,
                                  image_info,
                                  wait=False)
        self.client._command.assert_called_once_with(node=self.node,
                                         method='standby.prepare_image',
                                         params=params,
                                         wait=False)

    @mock.patch('uuid.uuid4', mock.MagicMock(return_value='uuid'))
    def test_prepare_image_with_configdrive(self):
        self.client._command = mock.Mock()
        configdrive_url = 'http://swift/configdrive'
        self.node.instance_info['configdrive'] = configdrive_url
        image_info = {'image_id': 'image'}
        params = {
            'image_info': image_info,
            'configdrive': configdrive_url,
        }

        self.client.prepare_image(self.node,
                                  image_info,
                                  wait=False)
        self.client._command.assert_called_once_with(node=self.node,
                                         method='standby.prepare_image',
                                         params=params,
                                         wait=False)
