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
"""
Tests for the RequestLogMiddleware
"""

from unittest import mock

from ironic.api.middleware import request_log
from ironic.tests import base


class TestRequestLogMiddleware(base.TestCase):
    """Test cases for RequestLogMiddleware."""

    def setUp(self):
        super(TestRequestLogMiddleware, self).setUp()

        # Create a mock application
        self.mock_app = mock.Mock()
        self.mock_app.return_value = [b'response body']

        # Create the middleware instance
        self.middleware = request_log.RequestLogMiddleware(self.mock_app)

        # Mock the logger
        self.mock_log = mock.patch.object(
            request_log, 'LOG', autospec=True
        ).start()

        self.template = ("%(source_ip)s - %(method)s %(path)s - %(status)s "
                         "(%(duration)sms)")

        # Mock time for consistent timing tests
        self.mock_time = mock.patch.object(
            request_log, 'time', autospec=True
        ).start()
        self.mock_time.time.side_effect = [1000.0, 1000.5]  # 500ms duration

    def test_successful_get_request(self):
        """Test logging of a successful GET request."""
        environ = {
            'REQUEST_METHOD': 'GET',
            'PATH_INFO': '/v1/nodes',
            'QUERY_STRING': ''
        }

        def start_response(status, headers, exc_info=None):
            return None

        # Configure mock app to call start_response with 200 OK
        def mock_app_call(env, sr):
            sr('200 OK', [('Content-Type', 'application/json')])
            return [b'response']

        self.mock_app.side_effect = mock_app_call

        # Call the middleware
        response = self.middleware(environ, start_response)

        # Verify the response is returned correctly
        self.assertEqual(response, [b'response'])

        # Verify the log was called with correct parameters
        self.mock_log.info.assert_called_once_with(
            self.template,
            {'method': 'GET',
             'path': '/v1/nodes',
             'status': 200,
             'duration': 500.0,
             'source_ip': 'unknown'}
        )

    def test_post_request_with_query_string(self):
        """Test logging of a POST request with query parameters."""
        environ = {
            'REQUEST_METHOD': 'POST',
            'PATH_INFO': '/v1/nodes',
            'QUERY_STRING': 'limit=10&marker=abc'
        }

        def start_response(status, headers, exc_info=None):
            return None

        def mock_app_call(env, sr):
            sr('201 Created', [('Content-Type', 'application/json')])
            return [b'created']

        self.mock_app.side_effect = mock_app_call

        response = self.middleware(environ, start_response)

        self.assertEqual(response, [b'created'])

        self.mock_log.info.assert_called_once_with(
            self.template,
            {'method': 'POST',
             'path': '/v1/nodes?limit=10&marker=abc',
             'status': 201,
             'duration': 500.0,
             'source_ip': 'unknown'}
        )

    def test_error_response(self):
        """Test logging of an error response."""
        environ = {
            'REQUEST_METHOD': 'DELETE',
            'PATH_INFO': '/v1/nodes/123',
            'QUERY_STRING': ''
        }

        def start_response(status, headers, exc_info=None):
            return None

        def mock_app_call(env, sr):
            sr('404 Not Found', [('Content-Type', 'application/json')])
            return [b'not found']

        self.mock_app.side_effect = mock_app_call

        response = self.middleware(environ, start_response)

        self.assertEqual(response, [b'not found'])

        self.mock_log.info.assert_called_once_with(
            self.template,
            {'method': 'DELETE',
             'path': '/v1/nodes/123',
             'status': 404,
             'duration': 500.0,
             'source_ip': 'unknown'}
        )

    def test_invalid_status_code(self):
        """Test handling of invalid status code."""
        environ = {
            'REQUEST_METHOD': 'GET',
            'PATH_INFO': '/v1/nodes',
            'QUERY_STRING': ''
        }

        def start_response(status, headers, exc_info=None):
            return None

        def mock_app_call(env, sr):
            sr('INVALID', [])  # Invalid status format
            return [b'response']

        self.mock_app.side_effect = mock_app_call

        response = self.middleware(environ, start_response)

        self.assertEqual(response, [b'response'])

        # Should log with status 'unknown' for invalid status
        self.mock_log.info.assert_called_once_with(
            self.template,
            {'method': 'GET',
             'path': '/v1/nodes',
             'status': 'unknown',
             'duration': 500.0,
             'source_ip': 'unknown'}
        )

    def test_generator_response(self):
        """Test handling of generator responses."""
        environ = {
            'REQUEST_METHOD': 'GET',
            'PATH_INFO': '/v1/nodes',
            'QUERY_STRING': ''
        }

        def start_response(status, headers, exc_info=None):
            return None

        def response_generator():
            yield b'part1'
            yield b'part2'

        def mock_app_call(env, sr):
            sr('200 OK', [])
            return response_generator()

        self.mock_app.side_effect = mock_app_call

        response = self.middleware(environ, start_response)

        # Response should be consumed and converted to list
        self.assertEqual(response, [b'part1', b'part2'])

        self.mock_log.info.assert_called_once()

    def test_missing_environ_values(self):
        """Test handling of missing environ values."""
        environ = {}  # Empty environ

        def start_response(status, headers, exc_info=None):
            return None

        def mock_app_call(env, sr):
            sr('200 OK', [])
            return [b'response']

        self.mock_app.side_effect = mock_app_call

        response = self.middleware(environ, start_response)

        self.assertEqual(response, [b'response'])

        # Should use empty strings for missing values
        self.mock_log.info.assert_called_once_with(
            self.template,
            {'method': '',
             'path': '',
             'status': 200,
             'duration': 500.0,
             'source_ip': 'unknown'}
        )

    def test_request_with_openstack_request_id(self):
        """Test logging with OpenStack request ID present."""
        environ = {
            'REQUEST_METHOD': 'GET',
            'PATH_INFO': '/v1/nodes',
            'QUERY_STRING': '',
            'openstack.request_id': 'req-12345678-1234-1234-1234-123456789abc',
            'openstack.global_request_id': 'req-99945678-1234-1234-1234-123456789zzz'  # noqa
        }

        def start_response(status, headers, exc_info=None):
            return None

        def mock_app_call(env, sr):
            sr('200 OK', [])
            return [b'response']

        self.mock_app.side_effect = mock_app_call

        response = self.middleware(environ, start_response)

        self.assertEqual(response, [b'response'])

        # Should log with source IP
        self.mock_log.info.assert_called_once_with(
            self.template,
            {'method': 'GET',
             'path': '/v1/nodes',
             'status': 200,
             'duration': 500.0,
             'source_ip': 'unknown'}
        )

    def test_exception_still_logs(self):
        """Test that logging happens even if app raises exception."""
        environ = {
            'REQUEST_METHOD': 'GET',
            'PATH_INFO': '/v1/nodes',
            'QUERY_STRING': ''
        }

        def start_response(status, headers, exc_info=None):
            return None

        # Mock app raises an exception
        self.mock_app.side_effect = ValueError("Test error")

        # The middleware should re-raise the exception but still log
        self.assertRaises(ValueError, self.middleware, environ, start_response)

        # Verify the log was still called (with unknown status since
        # start_response was never called)
        self.mock_log.info.assert_called_once_with(
            self.template,
            {'method': 'GET',
             'path': '/v1/nodes',
             'status': 'unknown',
             'duration': 500.0,
             'source_ip': 'unknown'}
        )
