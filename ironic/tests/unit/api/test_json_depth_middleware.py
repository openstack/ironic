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

"""Tests for the JSON depth and size limiting middleware."""

import io
import unittest
from unittest import mock

import webob

from ironic.api.middleware import json_depth


def _simple_app(environ, start_response):
    """Trivial WSGI app that returns 200 OK."""
    start_response('200 OK', [('Content-Type', 'application/json')])
    return [b'{"ok": true}']


def _make_request(method, path, body=None,
                  content_type='application/json'):
    """Build a webob.Request for testing."""
    req = webob.Request.blank(path)
    req.method = method
    if body is not None:
        if isinstance(body, str):
            body = body.encode('utf-8')
        req.body = body
        req.content_type = content_type
    return req


def _nested_object(depth):
    """Build a nested JSON object string to the given depth.

    depth=1 -> '{"a": 0}'
    depth=2 -> '{"a": {"a": 0}}'
    """
    return '{"a": ' * depth + '0' + '}' * depth


def _nested_array(depth):
    """Build a nested JSON array string to the given depth.

    depth=1 -> '[0]'
    depth=2 -> '[[0]]'
    """
    return '[' * depth + '0' + ']' * depth


class TestCheckDepth(unittest.TestCase):
    """Tests for the check_depth() scanning function."""

    def test_empty_body(self):
        self.assertTrue(json_depth.check_depth(b'', 1))

    def test_flat_object(self):
        self.assertTrue(
            json_depth.check_depth(b'{"a": 1}', 1))

    def test_flat_array(self):
        self.assertTrue(
            json_depth.check_depth(b'[1, 2, 3]', 1))

    def test_depth_exactly_at_limit(self):
        body = _nested_object(5).encode('utf-8')
        self.assertTrue(json_depth.check_depth(body, 5))

    def test_depth_one_over_limit(self):
        body = _nested_object(6).encode('utf-8')
        self.assertFalse(json_depth.check_depth(body, 5))

    def test_nested_arrays_at_limit(self):
        body = _nested_array(3).encode('utf-8')
        self.assertTrue(json_depth.check_depth(body, 3))

    def test_nested_arrays_over_limit(self):
        body = _nested_array(4).encode('utf-8')
        self.assertFalse(json_depth.check_depth(body, 3))

    def test_mixed_objects_and_arrays(self):
        # {"a": [{"b": [0]}]}  -> depth 4
        body = b'{"a": [{"b": [0]}]}'
        self.assertTrue(json_depth.check_depth(body, 4))
        self.assertFalse(json_depth.check_depth(body, 3))

    def test_brackets_inside_strings_ignored(self):
        # The brackets inside the string value should not count.
        body = b'{"a": "{{[[{{"}'
        self.assertTrue(json_depth.check_depth(body, 1))

    def test_escaped_quote_inside_string(self):
        # The escaped quote should not end the string, so the
        # brackets after it are still inside the string.
        body = b'{"a": "val\\"{{["}'
        self.assertTrue(json_depth.check_depth(body, 1))

    def test_backslash_before_quote_not_escape(self):
        # Double backslash then quote: the backslash is escaped,
        # so the quote ends the string. The next { is real.
        body = b'{"a": "val\\\\", "b": {"c": 0}}'
        # depth is 2: outer object + inner {"c": 0}
        self.assertTrue(json_depth.check_depth(body, 2))
        self.assertFalse(json_depth.check_depth(body, 1))

    def test_limit_of_one(self):
        self.assertTrue(
            json_depth.check_depth(b'{"a": 1}', 1))
        self.assertFalse(
            json_depth.check_depth(b'{"a": {"b": 1}}', 1))

    def test_very_deep_nesting(self):
        body = _nested_object(200).encode('utf-8')
        self.assertFalse(json_depth.check_depth(body, 25))

    def test_sibling_keys_do_not_increase_depth(self):
        body = b'{"a": 1, "b": 2, "c": 3}'
        self.assertTrue(json_depth.check_depth(body, 1))

    def test_array_of_objects(self):
        # [{"a":1}, {"b":2}]  -> depth 2
        body = b'[{"a": 1}, {"b": 2}]'
        self.assertTrue(json_depth.check_depth(body, 2))
        self.assertFalse(json_depth.check_depth(body, 1))

    def test_unclosed_brackets_large_payload(self):
        # 2000 opening brackets with no closers — malicious
        # payload that is far beyond any reasonable depth and
        # larger than typical read buffer sizes.
        body = (b'[' * 2000)
        self.assertFalse(json_depth.check_depth(body, 25))

    def test_unclosed_braces_large_payload(self):
        # Same attack shape with objects instead of arrays.
        body = (b'{"a":' * 2000)
        self.assertFalse(json_depth.check_depth(body, 25))

    def test_mixed_unclosed_delimiters(self):
        # Alternating braces and brackets, all unclosed.
        body = (b'{' b'[') * 1000
        self.assertFalse(json_depth.check_depth(body, 25))

    def test_large_flat_payload_passes(self):
        # A wide but shallow array should not be rejected.
        body = b'[' + b','.join(b'0' for _ in range(5000)) + b']'
        self.assertTrue(json_depth.check_depth(body, 1))

    def test_wide_object_with_deep_nesting_at_end(self):
        # A dictionary with 1000 shallow keys followed by a
        # deeply nested value on the last key.  The depth
        # violation is buried far into the payload.
        shallow = b', '.join(
            b'"k%d": 0' % i for i in range(1000))
        deep = _nested_object(10).encode('utf-8')
        body = b'{' + shallow + b', "bad": ' + deep + b'}'
        # Outer object adds 1 level, so total = 11.
        self.assertTrue(json_depth.check_depth(body, 11))
        self.assertFalse(json_depth.check_depth(body, 10))

    def test_wide_array_with_deep_nesting_in_middle(self):
        # 500 flat elements, then a deeply nested object, then
        # 500 more flat elements.
        flat = b'0, ' * 500
        deep = _nested_object(8).encode('utf-8')
        body = b'[' + flat + deep + b', ' + flat + b'0]'
        # Array adds 1 level, so total = 9.
        self.assertTrue(json_depth.check_depth(body, 9))
        self.assertFalse(json_depth.check_depth(body, 8))


class TestJsonDepthMiddleware(unittest.TestCase):
    """Tests for the JsonDepthMiddleware WSGI middleware."""

    def setUp(self):
        self.mw = json_depth.JsonDepthMiddleware(
            _simple_app, max_depth=5)

    def test_get_no_body_passes_through(self):
        req = _make_request('GET', '/v1/nodes')
        resp = req.get_response(self.mw)
        self.assertEqual(200, resp.status_int)

    def test_delete_no_body_passes_through(self):
        req = _make_request('DELETE', '/v1/nodes/fake-uuid')
        resp = req.get_response(self.mw)
        self.assertEqual(200, resp.status_int)

    def test_get_with_deep_json_body_rejected(self):
        """GET with a JSON body is checked despite being non-standard."""
        body = _nested_object(6)
        req = _make_request('GET', '/v1/nodes', body=body)
        resp = req.get_response(self.mw)
        self.assertEqual(400, resp.status_int)

    def test_delete_with_deep_json_body_rejected(self):
        """DELETE with a JSON body is checked despite being non-standard."""
        body = _nested_object(6)
        req = _make_request('DELETE', '/v1/nodes/fake-uuid',
                            body=body)
        resp = req.get_response(self.mw)
        self.assertEqual(400, resp.status_int)

    def test_post_non_json_passes_through(self):
        req = _make_request(
            'POST', '/v1/nodes',
            body=b'not json at all',
            content_type='text/plain')
        resp = req.get_response(self.mw)
        self.assertEqual(200, resp.status_int)

    def test_post_empty_body_passes_through(self):
        req = _make_request('POST', '/v1/nodes')
        resp = req.get_response(self.mw)
        self.assertEqual(200, resp.status_int)

    def test_post_within_depth_limit(self):
        body = _nested_object(5)
        req = _make_request('POST', '/v1/nodes', body=body)
        resp = req.get_response(self.mw)
        self.assertEqual(200, resp.status_int)

    def test_post_exceeding_depth_limit(self):
        body = _nested_object(6)
        req = _make_request('POST', '/v1/nodes', body=body)
        resp = req.get_response(self.mw)
        self.assertEqual(400, resp.status_int)
        self.assertIn(b'faultstring', resp.body)
        self.assertIn(b'nested too deeply', resp.body)
        self.assertIn(b'contact the service administrator', resp.body)
        # The configured depth limit must not be disclosed.
        self.assertNotIn(b'5', resp.body)
        # Verify no double-encoded error_message wrapper.
        self.assertNotIn(b'error_message', resp.body)

    def test_put_exceeding_depth_limit(self):
        body = _nested_object(6)
        req = _make_request('PUT', '/v1/nodes/fake/states/provision',
                            body=body)
        resp = req.get_response(self.mw)
        self.assertEqual(400, resp.status_int)

    def test_patch_exceeding_depth_limit(self):
        body = _nested_object(6)
        req = _make_request('PATCH', '/v1/nodes/fake-uuid',
                            body=body)
        resp = req.get_response(self.mw)
        self.assertEqual(400, resp.status_int)

    def test_post_within_limit_body_still_readable(self):
        """Verify the body is rewound for downstream consumption."""
        original = b'{"a": 1}'

        consumed_body = []

        def capturing_app(environ, start_response):
            consumed_body.append(environ['wsgi.input'].read())
            start_response(
                '200 OK',
                [('Content-Type', 'application/json')])
            return [b'{}']

        mw = json_depth.JsonDepthMiddleware(
            capturing_app, max_depth=5)
        req = _make_request('POST', '/v1/chassis', body=original)
        req.get_response(mw)
        self.assertEqual(original, consumed_body[0])

    def test_response_content_type_is_json(self):
        body = _nested_object(6)
        req = _make_request('POST', '/v1/nodes', body=body)
        resp = req.get_response(self.mw)
        self.assertEqual('application/json',
                         resp.content_type)

    def test_default_max_depth(self):
        mw = json_depth.JsonDepthMiddleware(_simple_app)
        self.assertEqual(25, mw.max_depth)

    def test_deeply_nested_attack_payload(self):
        body = _nested_object(1000)
        req = _make_request('POST', '/v1/nodes', body=body)
        resp = req.get_response(self.mw)
        self.assertEqual(400, resp.status_int)

    def test_unclosed_brackets_attack_payload(self):
        """Ensure a payload of 2000 unclosed '[' is rejected."""
        body = b'[' * 2000
        req = _make_request('POST', '/v1/nodes', body=body)
        resp = req.get_response(self.mw)
        self.assertEqual(400, resp.status_int)

    def test_unclosed_braces_attack_payload(self):
        """Ensure a payload of 2000 unclosed '{' is rejected."""
        body = b'{' * 2000
        req = _make_request('POST', '/v1/nodes', body=body)
        resp = req.get_response(self.mw)
        self.assertEqual(400, resp.status_int)

    def test_wide_then_deep_payload_rejected(self):
        """A payload with 1000 shallow keys hiding a deep value."""
        mw = json_depth.JsonDepthMiddleware(
            _simple_app, max_depth=10)
        shallow = b', '.join(
            b'"k%d": 0' % i for i in range(1000))
        deep = _nested_object(10).encode('utf-8')
        body = b'{' + shallow + b', "bad": ' + deep + b'}'
        req = _make_request('POST', '/v1/nodes', body=body)
        resp = req.get_response(mw)
        # Outer brace + 10 nested = 11, exceeds limit of 10.
        self.assertEqual(400, resp.status_int)

    def test_unbalanced_brackets_2048(self):
        """A 2048-byte payload of nothing but '[' characters.

        This is entirely invalid JSON that would never pass schema
        validation, but it must be caught by the depth middleware
        before it reaches the recursive JSON parser.
        """
        body = b'[' * 2048
        req = _make_request('POST', '/v1/nodes', body=body)
        resp = req.get_response(self.mw)
        self.assertEqual(400, resp.status_int)


class TestIsProvisionPath(unittest.TestCase):
    """Tests for the _is_provision_path() helper."""

    def test_provision_path(self):
        self.assertTrue(json_depth._is_provision_path(
            '/v1/nodes/fake-uuid/states/provision'))

    def test_provision_path_with_node_name(self):
        self.assertTrue(json_depth._is_provision_path(
            '/v1/nodes/my-node/states/provision'))

    def test_provision_path_trailing_slash(self):
        self.assertTrue(json_depth._is_provision_path(
            '/v1/nodes/fake-uuid/states/provision/'))

    def test_root_path(self):
        self.assertFalse(
            json_depth._is_provision_path('/'))

    def test_nodes_list(self):
        self.assertFalse(
            json_depth._is_provision_path('/v1/nodes'))

    def test_node_detail(self):
        self.assertFalse(json_depth._is_provision_path(
            '/v1/nodes/fake-uuid'))

    def test_node_states(self):
        self.assertFalse(json_depth._is_provision_path(
            '/v1/nodes/fake-uuid/states'))

    def test_other_endpoint(self):
        self.assertFalse(
            json_depth._is_provision_path('/v1/chassis'))

    def test_empty_path(self):
        self.assertFalse(
            json_depth._is_provision_path(''))

    def test_ports_path(self):
        self.assertFalse(
            json_depth._is_provision_path('/v1/ports'))

    def test_node_power_state(self):
        self.assertFalse(json_depth._is_provision_path(
            '/v1/nodes/fake-uuid/states/power'))

    def test_provision_path_without_version_prefix(self):
        self.assertTrue(json_depth._is_provision_path(
            '/nodes/fake-uuid/states/provision'))

    def test_provision_path_without_version_prefix_name(self):
        self.assertTrue(json_depth._is_provision_path(
            '/nodes/my-node/states/provision'))


class TestIsInspectionPath(unittest.TestCase):
    """Tests for the _is_inspection_path() helper."""

    def test_continue_inspection(self):
        self.assertTrue(json_depth._is_inspection_path(
            '/v1/continue_inspection'))

    def test_continue_inspection_trailing_slash(self):
        self.assertTrue(json_depth._is_inspection_path(
            '/v1/continue_inspection/'))

    def test_root_path(self):
        self.assertFalse(
            json_depth._is_inspection_path('/'))

    def test_nodes_path(self):
        self.assertFalse(
            json_depth._is_inspection_path('/v1/nodes'))

    def test_provision_path(self):
        self.assertFalse(json_depth._is_inspection_path(
            '/v1/nodes/fake/states/provision'))

    def test_empty_path(self):
        self.assertFalse(
            json_depth._is_inspection_path(''))

    def test_heartbeat_path(self):
        self.assertFalse(json_depth._is_inspection_path(
            '/v1/heartbeat/fake-uuid'))

    def test_lookup_path(self):
        self.assertFalse(json_depth._is_inspection_path(
            '/v1/lookup'))

    def test_continue_inspection_without_version_prefix(self):
        self.assertTrue(json_depth._is_inspection_path(
            '/continue_inspection'))


class TestBodySizeCheck(unittest.TestCase):
    """Tests for body size limiting in the middleware."""

    def setUp(self):
        self.mw = json_depth.JsonDepthMiddleware(
            _simple_app, max_depth=25,
            max_body_size=1024,
            max_provision_size=65536,
            max_inspection_size=32768)

    def test_small_body_passes(self):
        body = b'{"a": 1}'
        req = _make_request('POST', '/v1/nodes', body=body)
        resp = req.get_response(self.mw)
        self.assertEqual(200, resp.status_int)

    def test_body_exceeding_global_limit(self):
        body = b'{"x": "' + b'a' * 2000 + b'"}'
        req = _make_request(
            'POST', '/v1/nodes', body=body)
        resp = req.get_response(self.mw)
        self.assertEqual(413, resp.status_int)
        self.assertIn(b'too large', resp.body)

    def test_body_at_exact_global_limit(self):
        padding = 1024 - len(b'{"x": ""}')
        body = b'{"x": "' + b'a' * padding + b'"}'
        req = _make_request(
            'POST', '/v1/nodes', body=body)
        resp = req.get_response(self.mw)
        self.assertEqual(200, resp.status_int)

    def test_provision_path_uses_larger_limit(self):
        """Body exceeds global but is under provision limit."""
        body = (b'{"target": "active", "configdrive": "'
                + b'a' * 2000 + b'"}')
        path = '/v1/nodes/fake-uuid/states/provision'
        req = _make_request('PUT', path, body=body)
        resp = req.get_response(self.mw)
        self.assertEqual(200, resp.status_int)

    def test_provision_path_exceeds_provision_limit(self):
        body = (b'{"target": "active", "configdrive": "'
                + b'a' * 70000 + b'"}')
        path = '/v1/nodes/fake-uuid/states/provision'
        req = _make_request('PUT', path, body=body)
        resp = req.get_response(self.mw)
        self.assertEqual(413, resp.status_int)

    def test_inspection_path_uses_larger_limit(self):
        """Body exceeds global but is under inspection limit."""
        body = b'{"inventory": "' + b'x' * 2000 + b'"}'
        path = '/v1/continue_inspection'
        req = _make_request('POST', path, body=body)
        resp = req.get_response(self.mw)
        self.assertEqual(200, resp.status_int)

    def test_inspection_path_exceeds_inspection_limit(self):
        body = b'{"inventory": "' + b'x' * 40000 + b'"}'
        path = '/v1/continue_inspection'
        req = _make_request('POST', path, body=body)
        resp = req.get_response(self.mw)
        self.assertEqual(413, resp.status_int)

    def test_no_size_check_when_not_configured(self):
        """No size rejection when max_body_size is None."""
        mw = json_depth.JsonDepthMiddleware(
            _simple_app, max_depth=25)
        body = b'{"x": "' + b'a' * 5000 + b'"}'
        req = _make_request(
            'POST', '/v1/nodes', body=body)
        resp = req.get_response(mw)
        self.assertEqual(200, resp.status_int)

    def test_non_json_bypasses_size_check(self):
        body = b'a' * 5000
        req = _make_request(
            'POST', '/v1/nodes', body=body,
            content_type='text/plain')
        resp = req.get_response(self.mw)
        self.assertEqual(200, resp.status_int)

    def test_413_response_content_type(self):
        body = b'{"x": "' + b'a' * 2000 + b'"}'
        req = _make_request(
            'POST', '/v1/nodes', body=body)
        resp = req.get_response(self.mw)
        self.assertEqual('application/json',
                         resp.content_type)

    def test_size_limit_not_disclosed(self):
        body = b'{"x": "' + b'a' * 2000 + b'"}'
        req = _make_request(
            'POST', '/v1/nodes', body=body)
        resp = req.get_response(self.mw)
        self.assertNotIn(b'1024', resp.body)

    def test_empty_body_bypasses_size_check(self):
        req = _make_request('POST', '/v1/nodes')
        resp = req.get_response(self.mw)
        self.assertEqual(200, resp.status_int)

    def test_size_checked_before_depth(self):
        """An oversized body is rejected as 413, not 400."""
        body = b'[' * 2000
        req = _make_request(
            'POST', '/v1/nodes', body=body)
        resp = req.get_response(self.mw)
        # Size check runs first, so 413, not 400.
        self.assertEqual(413, resp.status_int)

    def test_no_provision_size_falls_back_to_global(self):
        """Without provision limit, global applies everywhere."""
        mw = json_depth.JsonDepthMiddleware(
            _simple_app, max_depth=25,
            max_body_size=1024)
        body = (b'{"target": "active", "configdrive": "'
                + b'a' * 2000 + b'"}')
        path = '/v1/nodes/fake-uuid/states/provision'
        req = _make_request('PUT', path, body=body)
        resp = req.get_response(mw)
        self.assertEqual(413, resp.status_int)

    def test_get_with_oversized_json_body_rejected(self):
        """GET with an oversized body is also rejected."""
        body = b'{"x": "' + b'a' * 2000 + b'"}'
        req = _make_request(
            'GET', '/v1/nodes', body=body)
        resp = req.get_response(self.mw)
        self.assertEqual(413, resp.status_int)

    @mock.patch.object(json_depth, 'LOG', autospec=True)
    def test_inspection_rejection_logs_error(self, mock_log):
        """Inspection rejections are logged at error level."""
        body = b'{"inventory": "' + b'x' * 40000 + b'"}'
        path = '/v1/continue_inspection'
        req = _make_request('POST', path, body=body)
        req.get_response(self.mw)
        mock_log.error.assert_called_once()
        log_msg = mock_log.error.call_args[0][0]
        self.assertIn('inspection', log_msg.lower())
        self.assertIn(
            'max_json_body_size_inspection', log_msg)

    @mock.patch.object(json_depth, 'LOG', autospec=True)
    def test_normal_rejection_logs_warning(self, mock_log):
        """Non-inspection rejections use warning level."""
        body = b'{"x": "' + b'a' * 2000 + b'"}'
        req = _make_request(
            'POST', '/v1/nodes', body=body)
        req.get_response(self.mw)
        mock_log.warning.assert_called_once()
        mock_log.error.assert_not_called()


class TestNoContentLength(unittest.TestCase):
    """Tests for requests without a Content-Length header.

    Chunked transfer encoding and other scenarios may omit
    Content-Length.  The middleware must still enforce both
    size and depth limits by reading the body with a cap.
    """

    def setUp(self):
        self.mw = json_depth.JsonDepthMiddleware(
            _simple_app, max_depth=25,
            max_body_size=1024,
            max_provision_size=65536)

    def _environ_no_cl(self, path, body):
        """Build a WSGI environ with no Content-Length."""
        env = {
            'REQUEST_METHOD': 'POST',
            'PATH_INFO': path,
            'CONTENT_TYPE': 'application/json',
            'wsgi.input': io.BytesIO(body),
            'SERVER_NAME': 'localhost',
            'SERVER_PORT': '6385',
        }
        return env

    def test_small_body_no_content_length_passes(self):
        body = b'{"a": 1}'
        env = self._environ_no_cl('/v1/nodes', body)
        req = webob.Request(env)
        resp = req.get_response(self.mw)
        self.assertEqual(200, resp.status_int)

    def test_oversized_body_no_content_length_rejected(self):
        body = b'{"x": "' + b'a' * 2000 + b'"}'
        env = self._environ_no_cl('/v1/nodes', body)
        req = webob.Request(env)
        resp = req.get_response(self.mw)
        self.assertEqual(413, resp.status_int)

    def test_deep_body_no_content_length_rejected(self):
        """Depth check runs even without Content-Length."""
        body = _nested_object(30).encode('utf-8')
        env = self._environ_no_cl('/v1/nodes', body)
        req = webob.Request(env)
        resp = req.get_response(self.mw)
        self.assertEqual(400, resp.status_int)
        self.assertIn(b'nested too deeply', resp.body)

    def test_empty_body_no_content_length_passes(self):
        env = self._environ_no_cl('/v1/nodes', b'')
        req = webob.Request(env)
        resp = req.get_response(self.mw)
        self.assertEqual(200, resp.status_int)

    def test_provision_path_no_content_length(self):
        """Provision path uses larger limit even without CL."""
        body = (b'{"target": "active", "configdrive": "'
                + b'a' * 2000 + b'"}')
        path = '/v1/nodes/fake-uuid/states/provision'
        env = self._environ_no_cl(path, body)
        req = webob.Request(env)
        resp = req.get_response(self.mw)
        self.assertEqual(200, resp.status_int)

    def test_no_size_limit_reads_all_for_depth_check(self):
        """Without size limit, body is still depth-checked."""
        mw = json_depth.JsonDepthMiddleware(
            _simple_app, max_depth=5)
        body = _nested_object(10).encode('utf-8')
        env = self._environ_no_cl('/v1/nodes', body)
        req = webob.Request(env)
        resp = req.get_response(mw)
        self.assertEqual(400, resp.status_int)

    def test_body_at_exact_limit_no_content_length(self):
        """Body exactly at the limit should pass."""
        padding = 1024 - len(b'{"x": ""}')
        body = b'{"x": "' + b'a' * padding + b'"}'
        env = self._environ_no_cl('/v1/nodes', body)
        req = webob.Request(env)
        resp = req.get_response(self.mw)
        self.assertEqual(200, resp.status_int)

    def test_body_rewound_after_capped_read(self):
        """Body must be available downstream after a capped read."""
        original = b'{"a": 1}'
        consumed_body = []

        def capturing_app(environ, start_response):
            consumed_body.append(
                environ['wsgi.input'].read())
            start_response(
                '200 OK',
                [('Content-Type', 'application/json')])
            return [b'{}']

        mw = json_depth.JsonDepthMiddleware(
            capturing_app, max_depth=25,
            max_body_size=1024)
        env = self._environ_no_cl('/v1/nodes', original)
        req = webob.Request(env)
        req.get_response(mw)
        self.assertEqual(original, consumed_body[0])
