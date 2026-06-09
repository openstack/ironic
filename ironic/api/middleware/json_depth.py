#
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

"""Middleware to reject oversized or excessively nested JSON bodies.

Python's json.loads() uses recursive descent parsing. A maliciously
crafted deeply-nested payload can exhaust the call stack and crash the
API worker process with a RecursionError. This middleware checks the
Content-Length header and scans the raw request body bytes iteratively
before any JSON parser runs, rejecting payloads that exceed a
configurable body size or nesting depth.
"""

import io

from oslo_log import log

from ironic.api.middleware.request_log import get_real_ip

LOG = log.getLogger(__name__)

# Pre-built rejection body template. No json module usage — the
# structure is simple enough to express as a format string, and
# this module intentionally avoids importing json since it exists
# to guard against problems in the json parser itself.
# NOTE(TheJulia): Uses a flat JSON object with faultstring
# directly rather than double-encoding inside an error_message
# wrapper string.
_REJECT_BODY = (
    b'{"faultcode": "Client", "faultstring": '
    b'"Request body JSON is nested too deeply. '
    b'Please contact the service administrator."}'
)

_REJECT_SIZE_BODY = (
    b'{"faultcode": "Client", "faultstring": '
    b'"Request body is too large. '
    b'Please contact the service administrator."}'
)


def _is_provision_path(path):
    """Check if path matches the node provision state endpoint.

    The provision endpoint /v1/nodes/{ident}/states/provision
    may carry configdrive data and deploy steps, requiring a
    higher body size limit. Uses endswith() to handle both
    versioned (/v1/...) and unversioned paths.
    """
    return path.strip('/').endswith('states/provision')


def _is_inspection_path(path):
    """Check if path matches the continue_inspection endpoint.

    The continue_inspection endpoint receives inspection data
    from the ramdisk, which may include system logs and can be
    significantly larger than normal API requests. Uses
    endswith() to handle both versioned and unversioned paths.
    """
    return path.strip('/').endswith('continue_inspection')


class JsonDepthMiddleware(object):
    """Reject JSON request bodies that are too large or nested."""

    def __init__(self, app, max_depth=25,
                 max_body_size=None,
                 max_provision_size=None,
                 max_inspection_size=None):
        self.app = app
        self.max_depth = max_depth
        self.max_body_size = max_body_size
        self.max_provision_size = max_provision_size
        self.max_inspection_size = max_inspection_size

    def _size_limit(self, environ):
        """Return the effective body size limit for this request.

        :returns: size limit in bytes, or None if unconfigured.
        """
        if self.max_body_size is None:
            return None
        path = environ.get('PATH_INFO', '')
        if (self.max_provision_size is not None
                and _is_provision_path(path)):
            return self.max_provision_size
        if (self.max_inspection_size is not None
                and _is_inspection_path(path)):
            return self.max_inspection_size
        return self.max_body_size

    def __call__(self, environ, start_response):
        # NOTE(TheJulia): Always evaluate if there is a body
        # payload, regardless of method to be more defensive
        # just in case. While sending a body with GET or DELETE
        # is against RFC 7231, it has been observed in practice.
        content_type = environ.get('CONTENT_TYPE', '')
        if 'json' not in content_type:
            return self.app(environ, start_response)

        try:
            length = int(environ.get('CONTENT_LENGTH', 0))
        except (ValueError, TypeError):
            length = 0

        limit = self._size_limit(environ)

        # Fast-path: reject before reading when Content-Length
        # is known and exceeds the limit.
        if length > 0 and limit is not None and length > limit:
            self._log_size_rejection(
                environ, length, limit)
            return self._reject_size(start_response)

        # Read the body.  When Content-Length is present, read
        # exactly that many bytes.  When it is absent (e.g.
        # chunked transfer encoding), cap the read at the size
        # limit to prevent unbounded memory allocation.
        if length > 0:
            body = environ['wsgi.input'].read(length)
        elif limit is not None:
            # Read one byte beyond the limit so we can
            # distinguish "at limit" from "over limit".
            body = environ['wsgi.input'].read(limit + 1)
        else:
            # No Content-Length and no size limit configured
            # (e.g. internal JSON-RPC).  Read everything so
            # the depth check still runs.
            body = environ['wsgi.input'].read()

        if not body:
            return self.app(environ, start_response)

        # Post-read size check for chunked transfers where
        # Content-Length was absent.
        if limit is not None and len(body) > limit:
            self._log_size_rejection(
                environ, len(body), limit)
            return self._reject_size(start_response)

        # Rewind so downstream middleware and Pecan can still
        # read the body.
        environ['wsgi.input'] = io.BytesIO(body)

        if not check_depth(body, self.max_depth):
            LOG.warning(
                'Rejected request from %(ip)s to %(path)s: '
                'JSON nesting depth exceeds %(limit)d',
                {'ip': get_real_ip(environ) or 'unknown',
                 'path': environ.get('PATH_INFO', '?'),
                 'limit': self.max_depth})
            return self._reject(start_response)

        return self.app(environ, start_response)

    def _log_size_rejection(self, environ, size, limit):
        ip = get_real_ip(environ) or 'unknown'
        path = environ.get('PATH_INFO', '?')
        if _is_inspection_path(path):
            # NOTE(TheJulia): Inspection data can be very large
            # when the ramdisk includes system logs such as the
            # journal.  This is almost certainly not an attack,
            # and the operator likely has no way to diagnose the
            # failure without checking the console of the node
            # being inspected.  Log loudly so they know to
            # increase [api]max_json_body_size_inspection.
            LOG.error(
                'Rejected inspection data from %(ip)s: '
                'body size %(size)d exceeds '
                '[api]max_json_body_size_inspection '
                '(%(limit)d). The ramdisk may be '
                'submitting large system logs. Increase '
                'the limit or reduce the data collected '
                'by the ramdisk.',
                {'ip': ip,
                 'size': size,
                 'limit': limit})
        else:
            LOG.warning(
                'Rejected request from %(ip)s to '
                '%(path)s: body size %(size)d '
                'exceeds limit %(limit)d',
                {'ip': ip,
                 'path': path,
                 'size': size,
                 'limit': limit})

    def _reject(self, start_response):
        body = _REJECT_BODY
        start_response(
            '400 Bad Request',
            [('Content-Type', 'application/json'),
             ('Content-Length', str(len(body)))])
        return [body]

    def _reject_size(self, start_response):
        body = _REJECT_SIZE_BODY
        start_response(
            '413 Request Entity Too Large',
            [('Content-Type', 'application/json'),
             ('Content-Length', str(len(body)))])
        return [body]


def check_depth(raw, max_depth):
    """Check that JSON nesting depth does not exceed max_depth.

    Scans raw bytes iteratively with no recursion. Tracks string
    boundaries and escape sequences so that brackets inside JSON
    string values are not counted.

    :param raw: Raw JSON bytes.
    :param max_depth: Maximum allowed nesting depth.
    :returns: True if depth is within the limit, False otherwise.
    """
    depth = 0
    in_string = False
    escape = False

    for byte in raw:
        if escape:
            escape = False
            continue

        # byte is an int when iterating over a bytes object.
        char = chr(byte)

        if in_string:
            if char == '\\':
                escape = True
            elif char == '"':
                in_string = False
            continue

        if char == '"':
            in_string = True
        elif char in ('{', '['):
            depth += 1
            if depth > max_depth:
                return False
        elif char in ('}', ']'):
            depth -= 1

    return True
