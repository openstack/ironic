# Copyright 2024 Red Hat, Inc.
# All Rights Reserved.
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

"""Shared helpers for the async Redfish unit tests."""

import json
from unittest import mock


def json_response(json_data=None, status_code=200, headers=None, etag=None):
    """Build a mock HTTP response carrying the given JSON body.

    Every AsyncConnector verb, including get(), returns the response
    object rather than the parsed body, so that callers can reach the
    headers and status code. Tests must therefore mock the connector
    with something exposing .json(), .headers and .status_code rather
    than with a bare dict.

    :param json_data: Object returned by the response's json() method.
    :param status_code: HTTP status code of the response.
    :param headers: Optional dict of response headers.
    :param etag: Optional ETag, added to the response headers.
    :returns: A mock response object.
    """
    headers = dict(headers or {})
    if etag is not None:
        headers['ETag'] = etag

    response = mock.Mock()
    response.status_code = status_code
    response.headers = headers
    response.json.return_value = json_data
    response.content = (b'' if json_data is None
                        else json.dumps(json_data).encode())
    return response
