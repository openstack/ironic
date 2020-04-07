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

import fixtures
import oslo_messaging
import webob

from ironic.common import context as ir_ctx
from ironic.common import exception
from ironic.common.json_rpc import client
from ironic.common.json_rpc import server
from ironic import objects
from ironic.objects import base as objects_base
from ironic.tests import base as test_base
from ironic.tests.unit.db import utils as db_utils
from ironic.tests.unit.objects import utils as obj_utils


class FakeManager(object):

    def success(self, context, x, y=0):
        assert isinstance(context, ir_ctx.RequestContext)
        assert context.user_name == 'admin'
        return x - y

    def with_node(self, context, node):
        assert isinstance(context, ir_ctx.RequestContext)
        assert isinstance(node, objects.Node)
        node.extra['answer'] = 42
        return node

    def no_result(self, context):
        assert isinstance(context, ir_ctx.RequestContext)
        return None

    def no_context(self):
        return 42

    def fail(self, context, message):
        assert isinstance(context, ir_ctx.RequestContext)
        raise exception.IronicException(message)

    @oslo_messaging.expected_exceptions(exception.Invalid)
    def expected(self, context, message):
        assert isinstance(context, ir_ctx.RequestContext)
        raise exception.Invalid(message)

    def crash(self, context):
        raise RuntimeError('boom')

    def init_host(self, context):
        assert False, "This should not be exposed"

    def _private(self, context):
        assert False, "This should not be exposed"

    # This should not be exposed either
    value = 42


class TestService(test_base.TestCase):

    def setUp(self):
        super(TestService, self).setUp()
        self.config(auth_strategy='noauth', group='json_rpc')
        self.server_mock = self.useFixture(fixtures.MockPatch(
            'oslo_service.wsgi.Server', autospec=True)).mock

        self.serializer = objects_base.IronicObjectSerializer(is_server=True)
        self.service = server.WSGIService(FakeManager(), self.serializer)
        self.app = self.service._application
        self.ctx = {'user_name': 'admin'}

    def _request(self, name=None, params=None, expected_error=None,
                 request_id='abcd', **kwargs):
        body = {
            'jsonrpc': '2.0',
        }
        if request_id is not None:
            body['id'] = request_id
        if name is not None:
            body['method'] = name
        if params is not None:
            body['params'] = params
        if 'json_body' not in kwargs:
            kwargs['json_body'] = body
        kwargs.setdefault('method', 'POST')
        kwargs.setdefault('headers', {'Content-Type': 'application/json'})

        request = webob.Request.blank("/", **kwargs)
        response = request.get_response(self.app)
        self.assertEqual(response.status_code,
                         expected_error or (200 if request_id else 204))
        if request_id is not None:
            if expected_error:
                self.assertEqual(expected_error,
                                 response.json_body['error']['code'])
            else:
                return response.json_body
        else:
            self.assertFalse(response.text)

    def _check(self, body, result=None, error=None, request_id='abcd'):
        self.assertEqual('2.0', body.pop('jsonrpc'))
        self.assertEqual(request_id, body.pop('id'))
        if error is not None:
            self.assertEqual({'error': error}, body)
        else:
            self.assertEqual({'result': result}, body)

    def test_success(self):
        body = self._request('success', {'context': self.ctx, 'x': 42})
        self._check(body, result=42)

    def test_success_no_result(self):
        body = self._request('no_result', {'context': self.ctx})
        self._check(body, result=None)

    def test_notification(self):
        body = self._request('no_result', {'context': self.ctx},
                             request_id=None)
        self.assertIsNone(body)

    def test_no_context(self):
        body = self._request('no_context')
        self._check(body, result=42)

    def test_serialize_objects(self):
        node = obj_utils.get_test_node(self.context)
        node = self.serializer.serialize_entity(self.context, node)
        body = self._request('with_node', {'context': self.ctx, 'node': node})
        self.assertNotIn('error', body)
        self.assertIsInstance(body['result'], dict)
        node = self.serializer.deserialize_entity(self.context, body['result'])
        self.assertEqual({'answer': 42}, node.extra)

    def test_non_json_body(self):
        for body in (b'', b'???', b"\xc3\x28"):
            request = webob.Request.blank("/", method='POST', body=body)
            response = request.get_response(self.app)
            self._check(
                response.json_body,
                error={
                    'message': server.ParseError._msg_fmt,
                    'code': -32700,
                },
                request_id=None)

    def test_invalid_requests(self):
        bodies = [
            # Invalid requests with request ID.
            {'method': 'no_result', 'id': 'abcd',
             'params': {'context': self.ctx}},
            {'jsonrpc': '2.0', 'id': 'abcd', 'params': {'context': self.ctx}},
            # These do not count as notifications, since they're malformed.
            {'method': 'no_result', 'params': {'context': self.ctx}},
            {'jsonrpc': '2.0', 'params': {'context': self.ctx}},
            42,
            # We do not implement batched requests.
            [],
            [{'jsonrpc': '2.0', 'method': 'no_result',
              'params': {'context': self.ctx}}],
        ]
        for body in bodies:
            body = self._request(json_body=body)
            self._check(
                body,
                error={
                    'message': server.InvalidRequest._msg_fmt,
                    'code': -32600,
                },
                request_id=body.get('id'))

    def test_malformed_context(self):
        body = self._request(json_body={'jsonrpc': '2.0', 'id': 'abcd',
                                        'method': 'no_result',
                                        'params': {'context': 42}})
        self._check(
            body,
            error={
                'message': 'Context must be a dictionary, if provided',
                'code': -32602,
            })

    def test_expected_failure(self):
        body = self._request('fail', {'context': self.ctx,
                                      'message': 'some error'})
        self._check(body,
                    error={
                        'message': 'some error',
                        'code': 500,
                        'data': {
                            'class': 'ironic_lib.exception.IronicException'
                        }
                    })

    def test_expected_failure_oslo(self):
        # Check that exceptions wrapped by oslo's expected_exceptions get
        # unwrapped correctly.
        body = self._request('expected', {'context': self.ctx,
                                          'message': 'some error'})
        self._check(body,
                    error={
                        'message': 'some error',
                        'code': 400,
                        'data': {
                            'class': 'ironic.common.exception.Invalid'
                        }
                    })

    @mock.patch.object(server.LOG, 'exception', autospec=True)
    def test_unexpected_failure(self, mock_log):
        body = self._request('crash', {'context': self.ctx})
        self._check(body,
                    error={
                        'message': 'boom',
                        'code': 500,
                    })
        self.assertTrue(mock_log.called)

    def test_method_not_found(self):
        body = self._request('banana', {'context': self.ctx})
        self._check(body,
                    error={
                        'message': 'Method banana was not found',
                        'code': -32601,
                    })

    def test_no_blacklisted_methods(self):
        for name in ('__init__', '_private', 'init_host', 'value'):
            body = self._request(name, {'context': self.ctx})
            self._check(body,
                        error={
                            'message': 'Method %s was not found' % name,
                            'code': -32601,
                        })

    def test_missing_argument(self):
        body = self._request('success', {'context': self.ctx})
        # The exact error message depends on the Python version
        self.assertEqual(-32602, body['error']['code'])
        self.assertNotIn('result', body)

    def test_method_not_post(self):
        self._request('success', {'context': self.ctx, 'x': 42},
                      method='GET', expected_error=405)

    def test_authenticated(self):
        self.config(auth_strategy='keystone', group='json_rpc')
        self.service = server.WSGIService(FakeManager(), self.serializer)
        self.app = self.server_mock.call_args[0][2]
        self._request('success', {'context': self.ctx, 'x': 42},
                      expected_error=401)

    def test_authenticated_no_admin_role(self):
        self.config(auth_strategy='keystone', group='json_rpc')
        self._request('success', {'context': self.ctx, 'x': 42},
                      expected_error=403)

    @mock.patch.object(server.LOG, 'debug', autospec=True)
    def test_mask_secrets(self, mock_log):
        node = obj_utils.get_test_node(
            self.context, driver_info=db_utils.get_test_ipmi_info())
        node = self.serializer.serialize_entity(self.context, node)
        body = self._request('with_node', {'context': self.ctx, 'node': node})
        node = self.serializer.deserialize_entity(self.context, body['result'])
        logged_params = mock_log.call_args_list[0][0][2]
        logged_node = logged_params['node']['ironic_object.data']
        self.assertEqual('***', logged_node['driver_info']['ipmi_password'])
        logged_resp = mock_log.call_args_list[1][0][2]
        logged_node = logged_resp['ironic_object.data']
        self.assertEqual('***', logged_node['driver_info']['ipmi_password'])
        # The result is not affected, only logging
        self.assertEqual(db_utils.get_test_ipmi_info(), node.driver_info)


@mock.patch.object(client, '_get_session', autospec=True)
class TestClient(test_base.TestCase):

    def setUp(self):
        super(TestClient, self).setUp()
        self.serializer = objects_base.IronicObjectSerializer(is_server=True)
        self.client = client.Client(self.serializer)
        self.ctx_json = self.context.to_dict()

    def test_can_send_version(self, mock_session):
        self.assertTrue(self.client.can_send_version('1.42'))
        self.client = client.Client(self.serializer, version_cap='1.42')
        self.assertTrue(self.client.can_send_version('1.42'))
        self.assertTrue(self.client.can_send_version('1.0'))
        self.assertFalse(self.client.can_send_version('1.99'))
        self.assertFalse(self.client.can_send_version('2.0'))

    def test_call_success(self, mock_session):
        response = mock_session.return_value.post.return_value
        response.json.return_value = {
            'jsonrpc': '2.0',
            'result': 42
        }
        cctx = self.client.prepare('foo.example.com')
        self.assertEqual('example.com', cctx.host)
        result = cctx.call(self.context, 'do_something', answer=42)
        self.assertEqual(42, result)
        mock_session.return_value.post.assert_called_once_with(
            'http://example.com:8089',
            json={'jsonrpc': '2.0',
                  'method': 'do_something',
                  'params': {'answer': 42, 'context': self.ctx_json},
                  'id': self.context.request_id})

    def test_call_success_with_version(self, mock_session):
        response = mock_session.return_value.post.return_value
        response.json.return_value = {
            'jsonrpc': '2.0',
            'result': 42
        }
        cctx = self.client.prepare('foo.example.com', version='1.42')
        self.assertEqual('example.com', cctx.host)
        result = cctx.call(self.context, 'do_something', answer=42)
        self.assertEqual(42, result)
        mock_session.return_value.post.assert_called_once_with(
            'http://example.com:8089',
            json={'jsonrpc': '2.0',
                  'method': 'do_something',
                  'params': {'answer': 42, 'context': self.ctx_json,
                             'rpc.version': '1.42'},
                  'id': self.context.request_id})

    def test_call_success_with_version_and_cap(self, mock_session):
        self.client = client.Client(self.serializer, version_cap='1.99')
        response = mock_session.return_value.post.return_value
        response.json.return_value = {
            'jsonrpc': '2.0',
            'result': 42
        }
        cctx = self.client.prepare('foo.example.com', version='1.42')
        self.assertEqual('example.com', cctx.host)
        result = cctx.call(self.context, 'do_something', answer=42)
        self.assertEqual(42, result)
        mock_session.return_value.post.assert_called_once_with(
            'http://example.com:8089',
            json={'jsonrpc': '2.0',
                  'method': 'do_something',
                  'params': {'answer': 42, 'context': self.ctx_json,
                             'rpc.version': '1.42'},
                  'id': self.context.request_id})

    def test_cast_success(self, mock_session):
        cctx = self.client.prepare('foo.example.com')
        self.assertEqual('example.com', cctx.host)
        result = cctx.cast(self.context, 'do_something', answer=42)
        self.assertIsNone(result)
        mock_session.return_value.post.assert_called_once_with(
            'http://example.com:8089',
            json={'jsonrpc': '2.0',
                  'method': 'do_something',
                  'params': {'answer': 42, 'context': self.ctx_json}})

    def test_cast_success_with_version(self, mock_session):
        cctx = self.client.prepare('foo.example.com', version='1.42')
        self.assertEqual('example.com', cctx.host)
        result = cctx.cast(self.context, 'do_something', answer=42)
        self.assertIsNone(result)
        mock_session.return_value.post.assert_called_once_with(
            'http://example.com:8089',
            json={'jsonrpc': '2.0',
                  'method': 'do_something',
                  'params': {'answer': 42, 'context': self.ctx_json,
                             'rpc.version': '1.42'}})

    def test_call_serialization(self, mock_session):
        node = obj_utils.get_test_node(self.context)
        node_json = self.serializer.serialize_entity(self.context, node)
        response = mock_session.return_value.post.return_value
        response.json.return_value = {
            'jsonrpc': '2.0',
            'result': node_json
        }
        cctx = self.client.prepare('foo.example.com')
        self.assertEqual('example.com', cctx.host)
        result = cctx.call(self.context, 'do_something', node=node)
        self.assertIsInstance(result, objects.Node)
        self.assertEqual(result.uuid, node.uuid)
        mock_session.return_value.post.assert_called_once_with(
            'http://example.com:8089',
            json={'jsonrpc': '2.0',
                  'method': 'do_something',
                  'params': {'node': node_json, 'context': self.ctx_json},
                  'id': self.context.request_id})

    def test_call_failure(self, mock_session):
        response = mock_session.return_value.post.return_value
        response.json.return_value = {
            'jsonrpc': '2.0',
            'error': {
                'code': 418,
                'message': 'I am a teapot',
                'data': {
                    'class': 'ironic.common.exception.Invalid'
                }
            }
        }
        cctx = self.client.prepare('foo.example.com')
        self.assertEqual('example.com', cctx.host)
        # Make sure that the class is restored correctly for expected errors.
        exc = self.assertRaises(exception.Invalid,
                                cctx.call,
                                self.context, 'do_something', answer=42)
        # Code from the body has priority over one in the class.
        self.assertEqual(418, exc.code)
        self.assertIn('I am a teapot', str(exc))
        mock_session.return_value.post.assert_called_once_with(
            'http://example.com:8089',
            json={'jsonrpc': '2.0',
                  'method': 'do_something',
                  'params': {'answer': 42, 'context': self.ctx_json},
                  'id': self.context.request_id})

    def test_call_unexpected_failure(self, mock_session):
        response = mock_session.return_value.post.return_value
        response.json.return_value = {
            'jsonrpc': '2.0',
            'error': {
                'code': 500,
                'message': 'AttributeError',
            }
        }
        cctx = self.client.prepare('foo.example.com')
        self.assertEqual('example.com', cctx.host)
        exc = self.assertRaises(exception.IronicException,
                                cctx.call,
                                self.context, 'do_something', answer=42)
        self.assertEqual(500, exc.code)
        self.assertIn('Unexpected error', str(exc))
        mock_session.return_value.post.assert_called_once_with(
            'http://example.com:8089',
            json={'jsonrpc': '2.0',
                  'method': 'do_something',
                  'params': {'answer': 42, 'context': self.ctx_json},
                  'id': self.context.request_id})

    def test_call_failure_with_foreign_class(self, mock_session):
        # This should not happen, but provide an additional safeguard
        response = mock_session.return_value.post.return_value
        response.json.return_value = {
            'jsonrpc': '2.0',
            'error': {
                'code': 500,
                'message': 'AttributeError',
                'data': {
                    'class': 'AttributeError'
                }
            }
        }
        cctx = self.client.prepare('foo.example.com')
        self.assertEqual('example.com', cctx.host)
        exc = self.assertRaises(exception.IronicException,
                                cctx.call,
                                self.context, 'do_something', answer=42)
        self.assertEqual(500, exc.code)
        self.assertIn('Unexpected error', str(exc))
        mock_session.return_value.post.assert_called_once_with(
            'http://example.com:8089',
            json={'jsonrpc': '2.0',
                  'method': 'do_something',
                  'params': {'answer': 42, 'context': self.ctx_json},
                  'id': self.context.request_id})

    def test_cast_failure(self, mock_session):
        # Cast cannot return normal failures, but make sure we ignore them even
        # if server sends something in violation of the protocol (or because
        # it's a low-level error like HTTP Forbidden).
        response = mock_session.return_value.post.return_value
        response.json.return_value = {
            'jsonrpc': '2.0',
            'error': {
                'code': 418,
                'message': 'I am a teapot',
                'data': {
                    'class': 'ironic.common.exception.IronicException'
                }
            }
        }
        cctx = self.client.prepare('foo.example.com')
        self.assertEqual('example.com', cctx.host)
        result = cctx.cast(self.context, 'do_something', answer=42)
        self.assertIsNone(result)
        mock_session.return_value.post.assert_called_once_with(
            'http://example.com:8089',
            json={'jsonrpc': '2.0',
                  'method': 'do_something',
                  'params': {'answer': 42, 'context': self.ctx_json}})

    def test_call_failure_with_version_and_cap(self, mock_session):
        self.client = client.Client(self.serializer, version_cap='1.42')
        cctx = self.client.prepare('foo.example.com', version='1.99')
        self.assertRaisesRegex(RuntimeError,
                               "requested version 1.99, maximum allowed "
                               "version is 1.42",
                               cctx.call, self.context, 'do_something',
                               answer=42)
        self.assertFalse(mock_session.return_value.post.called)

    @mock.patch.object(client.LOG, 'debug', autospec=True)
    def test_mask_secrets(self, mock_log, mock_session):
        request = {
            'redfish_username': 'admin',
            'redfish_password': 'passw0rd'
        }
        body = """{
            "jsonrpc": "2.0",
            "result": {
                "driver_info": {
                    "ipmi_username": "admin",
                    "ipmi_password": "passw0rd"
                }
            }
        }"""
        response = mock_session.return_value.post.return_value
        response.text = body
        cctx = self.client.prepare('foo.example.com')
        cctx.cast(self.context, 'do_something', node=request)
        mock_session.return_value.post.assert_called_once_with(
            'http://example.com:8089',
            json={'jsonrpc': '2.0',
                  'method': 'do_something',
                  'params': {'node': request, 'context': self.ctx_json}})
        self.assertEqual(2, mock_log.call_count)
        node = mock_log.call_args_list[0][0][2]['params']['node']
        self.assertEqual(node, {'redfish_username': 'admin',
                                'redfish_password': '***'})
        resp_text = mock_log.call_args_list[1][0][2]
        self.assertEqual(body.replace('passw0rd', '***'), resp_text)
