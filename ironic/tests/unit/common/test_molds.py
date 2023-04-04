# Copyright (c) 2021 Dell Inc. or its subsidiaries.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

import json
from unittest import mock

from oslo_config import cfg
import requests

from ironic.common import exception
from ironic.common import molds
from ironic.common import swift
from ironic.conductor import task_manager
from ironic.tests.unit.db import base as db_base
from ironic.tests.unit.objects import utils as obj_utils


class ConfigurationMoldTestCase(db_base.DbTestCase):

    def setUp(self):
        super(ConfigurationMoldTestCase, self).setUp()
        self.node = obj_utils.create_test_node(self.context)

    @mock.patch.object(swift, 'get_swift_session', autospec=True)
    @mock.patch.object(requests, 'put', autospec=True)
    def test_save_configuration_swift(self, mock_put, mock_swift):
        mock_session = mock.Mock()
        mock_session.get_token.return_value = 'token'
        mock_swift.return_value = mock_session
        cfg.CONF.set_override('storage', 'swift', 'molds')
        url = 'https://example.com/file1'
        data = {'key': 'value'}

        with task_manager.acquire(self.context, self.node.uuid) as task:
            molds.save_configuration(task, url, data)

        mock_put.assert_called_once_with(url, '{\n  "key": "value"\n}',
                                         headers={'X-Auth-Token': 'token'},
                                         timeout=60)

    @mock.patch.object(swift, 'get_swift_session', autospec=True)
    @mock.patch.object(requests, 'put', autospec=True)
    def test_save_configuration_swift_noauth(self, mock_put, mock_swift):
        mock_session = mock.Mock()
        mock_session.get_token.return_value = None
        mock_swift.return_value = mock_session
        cfg.CONF.set_override('storage', 'swift', 'molds')
        url = 'https://example.com/file1'
        data = {'key': 'value'}

        with task_manager.acquire(self.context, self.node.uuid) as task:
            self.assertRaises(
                exception.IronicException,
                molds.save_configuration,
                task, url, data)

    @mock.patch.object(requests, 'put', autospec=True)
    def test_save_configuration_http(self, mock_put):
        cfg.CONF.set_override('storage', 'http', 'molds')
        cfg.CONF.set_override('user', 'user', 'molds')
        cfg.CONF.set_override('password', 'password', 'molds')
        url = 'https://example.com/file1'
        data = {'key': 'value'}

        with task_manager.acquire(self.context, self.node.uuid) as task:
            molds.save_configuration(task, url, data)

            mock_put.assert_called_once_with(
                url, '{\n  "key": "value"\n}',
                headers={'Authorization': 'Basic dXNlcjpwYXNzd29yZA=='},
                timeout=60)

    @mock.patch.object(requests, 'put', autospec=True)
    def test_save_configuration_http_noauth(self, mock_put):
        cfg.CONF.set_override('storage', 'http', 'molds')
        cfg.CONF.set_override('user', None, 'molds')
        cfg.CONF.set_override('password', None, 'molds')
        url = 'https://example.com/file1'
        data = {'key': 'value'}

        with task_manager.acquire(self.context, self.node.uuid) as task:
            molds.save_configuration(task, url, data)
            mock_put.assert_called_once_with(
                url, '{\n  "key": "value"\n}',
                headers=None,
                timeout=60)

    @mock.patch.object(requests, 'put', autospec=True)
    def test_save_configuration_http_error(self, mock_put):
        cfg.CONF.set_override('storage', 'http', 'molds')
        cfg.CONF.set_override('user', 'user', 'molds')
        cfg.CONF.set_override('password', 'password', 'molds')
        response = mock.MagicMock()
        response.status_code = 404
        response.raise_for_status.side_effect = requests.exceptions.HTTPError
        mock_put.return_value = response

        with task_manager.acquire(self.context, self.node.uuid) as task:
            self.assertRaises(
                requests.exceptions.HTTPError,
                molds.save_configuration,
                task,
                'https://example.com/file2',
                {'key': 'value'})
            mock_put.assert_called_once_with(
                'https://example.com/file2', '{\n  "key": "value"\n}',
                headers={'Authorization': 'Basic dXNlcjpwYXNzd29yZA=='},
                timeout=60)

    @mock.patch.object(requests, 'put', autospec=True)
    def test_save_configuration_connection_error(self, mock_put):
        cfg.CONF.set_override('storage', 'http', 'molds')
        cfg.CONF.set_override('user', 'user', 'molds')
        cfg.CONF.set_override('password', 'password', 'molds')
        cfg.CONF.set_override('retry_interval', 0, 'molds')
        cfg.CONF.set_override('retry_attempts', 3, 'molds')
        response = mock.MagicMock()
        mock_put.side_effect = [
            requests.exceptions.ConnectTimeout,
            requests.exceptions.ConnectionError,
            response]

        with task_manager.acquire(self.context, self.node.uuid) as task:
            molds.save_configuration(
                task, 'https://example.com/file2', {'key': 'value'})
            mock_put.assert_called_with(
                'https://example.com/file2', '{\n  "key": "value"\n}',
                headers={'Authorization': 'Basic dXNlcjpwYXNzd29yZA=='},
                timeout=60)
            self.assertEqual(mock_put.call_count, 3)

    @mock.patch.object(requests, 'put', autospec=True)
    def test_save_configuration_connection_error_exceeded(self, mock_put):
        cfg.CONF.set_override('storage', 'http', 'molds')
        cfg.CONF.set_override('user', 'user', 'molds')
        cfg.CONF.set_override('password', 'password', 'molds')
        cfg.CONF.set_override('retry_interval', 0, 'molds')
        cfg.CONF.set_override('retry_attempts', 2, 'molds')
        mock_put.side_effect = [
            requests.exceptions.ConnectTimeout,
            requests.exceptions.ConnectionError]

        with task_manager.acquire(self.context, self.node.uuid) as task:
            self.assertRaises(
                requests.exceptions.ConnectionError,
                molds.save_configuration,
                task,
                'https://example.com/file2',
                {'key': 'value'})
            mock_put.assert_called_with(
                'https://example.com/file2', '{\n  "key": "value"\n}',
                headers={'Authorization': 'Basic dXNlcjpwYXNzd29yZA=='},
                timeout=60)
            self.assertEqual(mock_put.call_count, 2)

    @mock.patch.object(swift, 'get_swift_session', autospec=True)
    @mock.patch.object(requests, 'get', autospec=True)
    def test_get_configuration_swift(self, mock_get, mock_swift):
        mock_session = mock.Mock()
        mock_session.get_token.return_value = 'token'
        mock_swift.return_value = mock_session
        cfg.CONF.set_override('storage', 'swift', 'molds')
        response = mock.MagicMock()
        response.status_code = 200
        response.content = "{'key': 'value'}"
        response.json.return_value = {'key': 'value'}
        mock_get.return_value = response
        url = 'https://example.com/file1'

        with task_manager.acquire(self.context, self.node.uuid) as task:
            result = molds.get_configuration(task, url)

            mock_get.assert_called_once_with(
                url, headers={'X-Auth-Token': 'token'},
                timeout=60)
            self.assertJsonEqual({'key': 'value'}, result)

    @mock.patch.object(swift, 'get_swift_session', autospec=True)
    @mock.patch.object(requests, 'get', autospec=True)
    def test_get_configuration_swift_noauth(self, mock_get, mock_swift):
        mock_session = mock.Mock()
        mock_session.get_token.return_value = None
        mock_swift.return_value = mock_session
        cfg.CONF.set_override('storage', 'swift', 'molds')
        url = 'https://example.com/file1'

        with task_manager.acquire(self.context, self.node.uuid) as task:
            self.assertRaises(
                exception.IronicException,
                molds.get_configuration,
                task, url)

    @mock.patch.object(requests, 'get', autospec=True)
    def test_get_configuration_http(self, mock_get):
        cfg.CONF.set_override('storage', 'http', 'molds')
        cfg.CONF.set_override('user', 'user', 'molds')
        cfg.CONF.set_override('password', 'password', 'molds')
        response = mock.MagicMock()
        response.status_code = 200
        response.content = "{'key': 'value'}"
        response.json.return_value = {'key': 'value'}
        mock_get.return_value = response
        url = 'https://example.com/file2'

        with task_manager.acquire(self.context, self.node.uuid) as task:
            result = molds.get_configuration(task, url)

            mock_get.assert_called_once_with(
                url, headers={'Authorization': 'Basic dXNlcjpwYXNzd29yZA=='},
                timeout=60)
            self.assertJsonEqual({"key": "value"}, result)

    @mock.patch.object(requests, 'get', autospec=True)
    def test_get_configuration_http_noauth(self, mock_get):
        cfg.CONF.set_override('storage', 'http', 'molds')
        cfg.CONF.set_override('user', None, 'molds')
        cfg.CONF.set_override('password', None, 'molds')
        response = mock.MagicMock()
        response.status_code = 200
        response.content = "{'key': 'value'}"
        response.json.return_value = {'key': 'value'}
        mock_get.return_value = response
        url = 'https://example.com/file2'

        with task_manager.acquire(self.context, self.node.uuid) as task:
            result = molds.get_configuration(task, url)

            mock_get.assert_called_once_with(url, headers=None, timeout=60)
            self.assertJsonEqual({"key": "value"}, result)

    @mock.patch.object(requests, 'get', autospec=True)
    def test_get_configuration_http_error(self, mock_get):
        cfg.CONF.set_override('storage', 'http', 'molds')
        cfg.CONF.set_override('user', 'user', 'molds')
        cfg.CONF.set_override('password', 'password', 'molds')
        response = mock.MagicMock()
        response.status_code = 404
        response.raise_for_status.side_effect = requests.exceptions.HTTPError
        mock_get.return_value = response

        with task_manager.acquire(self.context, self.node.uuid) as task:
            self.assertRaises(
                requests.exceptions.HTTPError,
                molds.get_configuration,
                task,
                'https://example.com/file2')
            mock_get.assert_called_once_with(
                'https://example.com/file2',
                headers={'Authorization': 'Basic dXNlcjpwYXNzd29yZA=='},
                timeout=60)

    @mock.patch.object(requests, 'get', autospec=True)
    def test_get_configuration_connection_error(self, mock_get):
        cfg.CONF.set_override('storage', 'http', 'molds')
        cfg.CONF.set_override('user', 'user', 'molds')
        cfg.CONF.set_override('password', 'password', 'molds')
        cfg.CONF.set_override('retry_interval', 0, 'molds')
        cfg.CONF.set_override('retry_attempts', 3, 'molds')
        response = mock.MagicMock()
        mock_get.side_effect = [
            requests.exceptions.ConnectTimeout,
            requests.exceptions.ConnectionError,
            response]

        with task_manager.acquire(self.context, self.node.uuid) as task:
            molds.get_configuration(
                task, 'https://example.com/file2')
            mock_get.assert_called_with(
                'https://example.com/file2',
                headers={'Authorization': 'Basic dXNlcjpwYXNzd29yZA=='},
                timeout=60)
            self.assertEqual(mock_get.call_count, 3)

    @mock.patch.object(requests, 'get', autospec=True)
    def test_get_configuration_mold_connection_error_exceeded(self, mock_get):
        cfg.CONF.set_override('storage', 'http', 'molds')
        cfg.CONF.set_override('user', 'user', 'molds')
        cfg.CONF.set_override('password', 'password', 'molds')
        cfg.CONF.set_override('retry_interval', 0, 'molds')
        cfg.CONF.set_override('retry_attempts', 2, 'molds')
        mock_get.side_effect = [
            requests.exceptions.ConnectTimeout,
            requests.exceptions.ConnectionError]

        with task_manager.acquire(self.context, self.node.uuid) as task:
            self.assertRaises(
                requests.exceptions.ConnectionError,
                molds.get_configuration,
                task,
                'https://example.com/file2')
            mock_get.assert_called_with(
                'https://example.com/file2',
                headers={'Authorization': 'Basic dXNlcjpwYXNzd29yZA=='},
                timeout=60)
            self.assertEqual(mock_get.call_count, 2)

    @mock.patch.object(requests, 'get', autospec=True)
    def test_get_configuration_empty(self, mock_get):
        cfg.CONF.set_override('storage', 'http', 'molds')
        response = mock.MagicMock()
        response.status_code = 200
        response.content = ''
        mock_get.return_value = response
        url = 'https://example.com/file2'

        with task_manager.acquire(self.context, self.node.uuid) as task:
            self.assertRaises(exception.IronicException,
                              molds.get_configuration, task, url)

    @mock.patch.object(requests, 'get', autospec=True)
    def test_get_configuration_invalid_json(self, mock_get):
        cfg.CONF.set_override('storage', 'http', 'molds')
        response = mock.MagicMock()
        response.status_code = 200
        response.content = 'not json'
        response.json.side_effect = json.decoder.JSONDecodeError(
            'Expecting value', 'not json', 0)
        mock_get.return_value = response
        url = 'https://example.com/file2'

        with task_manager.acquire(self.context, self.node.uuid) as task:
            self.assertRaises(exception.IronicException,
                              molds.get_configuration, task, url)
