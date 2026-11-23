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

"""Async Redfish client exceptions."""


class RedfishError(Exception):
    """Base exception for Redfish client errors."""

    message = None

    def __init__(self, **kwargs):
        if self.message and kwargs:
            self.message = self.message % kwargs

        super(RedfishError, self).__init__(self.message)


class ConnectionError(RedfishError):
    """Connection error with the Redfish service."""

    message = 'Unable to connect to %(url)s. Error: %(error)s'


class HTTPError(RedfishError):
    """HTTP error from Redfish service."""

    message = ('HTTP %(method)s %(url)s returned code %(status_code)s. '
               '%(body)s')

    def __init__(self, method, url, response):
        self.method = method
        self.url = url
        self.status_code = response.status_code if response else None
        try:
            body = response.json() if response else {}
        except Exception:
            body = response.text if response else ''

        super(HTTPError, self).__init__(
            method=method,
            url=url,
            status_code=self.status_code,
            body=body
        )


class AccessError(HTTPError):
    """Access denied error (HTTP 401/403)."""

    message = 'Access denied to %(url)s: %(body)s'


class ResourceNotFoundError(RedfishError):
    """Resource not found error (HTTP 404)."""

    message = 'Resource %(url)s not found'

    def __init__(self, method='GET', url=None, response=None):
        self.method = method
        self.url = url
        self.status_code = response.status_code if response else 404
        super(ResourceNotFoundError, self).__init__(url=url)


class BadRequestError(HTTPError):
    """Bad request error (HTTP 400)."""

    message = 'Bad request to %(url)s: %(body)s'


class ServerSideError(HTTPError):
    """Server-side error (HTTP 5xx)."""

    message = 'Server error at %(url)s: %(body)s'


class NotAcceptableError(HTTPError):
    """Not acceptable error (HTTP 406)."""

    message = 'Not acceptable at %(url)s: %(body)s'


class MissingAttributeError(RedfishError):
    """Missing attribute in resource."""

    message = 'Missing attribute %(attribute)s in %(resource)s'


class MalformedAttributeError(RedfishError):
    """Malformed attribute in resource."""

    message = 'Malformed attribute %(attribute)s in %(resource)s: %(error)s'


class MissingHeaderError(RedfishError):
    """Missing required header in response."""

    message = 'Missing required header %(header)s in response'


class UnknownDefaultError(RedfishError):
    """Cannot determine default resource from collection."""

    message = ('Cannot determine default resource: expected exactly 1 '
               'item in collection, found %(count)d')


__all__ = [
    'RedfishError',
    'ConnectionError',
    'HTTPError',
    'AccessError',
    'BadRequestError',
    'ServerSideError',
    'NotAcceptableError',
    'ResourceNotFoundError',
    'MissingAttributeError',
    'MalformedAttributeError',
    'MissingHeaderError',
    'UnknownDefaultError',
]
