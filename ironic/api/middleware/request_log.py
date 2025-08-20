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
Middleware to log API request details including timing, status codes,
and request information for debugging purposes.
"""
import collections.abc
import time

from oslo_log import log

LOG = log.getLogger('ironic.api')


def get_real_ip(environ):
    """Safely retrieves the real IP address from a WSGI request."""
    # Check for the X-Forwarded-For header, which can contain a list of IPs.
    # The client's IP is the first one in the list.
    if 'HTTP_X_FORWARDED_FOR' in environ:
        # The header value is a comma-separated string, e.g., "client, proxy"
        # We take the first IP, which is the original client.
        return environ['HTTP_X_FORWARDED_FOR'].split(',')[0].strip()

    # If X-Forwarded-For is not present, check for X-Real-IP.
    elif 'HTTP_X_REAL_IP' in environ:
        return environ['HTTP_X_REAL_IP']

    # If no proxy headers are present, fall back to REMOTE_ADDR.
    else:
        return environ.get('REMOTE_ADDR')


class RequestLogMiddleware(object):
    """Middleware to log request details for debugging."""

    def __init__(self, app):
        self.app = app

    def __call__(self, environ, start_response):
        # Capture request start time
        start_time = time.time()

        # Extract request details
        method = environ.get('REQUEST_METHOD', '')
        path = environ.get('PATH_INFO', '')
        query_string = environ.get('QUERY_STRING', '')

        # Build full path with query string if present
        full_path = path
        if query_string:
            full_path = f"{path}?{query_string}"

        # Capture response status
        status_code = None

        def logging_start_response(status, headers, exc_info=None):
            nonlocal status_code
            # Extract status code from status string (e.g., "200 OK")
            try:
                status_code = int(status.split(' ', 1)[0])
            except (ValueError, IndexError):
                status_code = 0
            return start_response(status, headers, exc_info)

        # Process the request
        try:
            response = self.app(environ, logging_start_response)
            # Ensure response is consumed if it's a generator
            if isinstance(response, collections.abc.Iterator):
                response = list(response)
            return response
        finally:
            # Calculate request duration
            duration = time.time() - start_time
            duration_ms = round(duration * 1000, 2)

            # Log the request details with request ID for traceability
            LOG.info("%(source_ip)s - %(method)s %(path)s - %(status)s (%("
                     "duration)sms)",
                     {'method': method,
                      'path': full_path,
                      'status': status_code or 'unknown',
                      'duration': duration_ms,
                      'source_ip': get_real_ip(environ) or 'unknown'})
