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

"""A simple JSON RPC client.

This client is compatible with any JSON RPC 2.0 implementation, including ours.
"""

import logging

from oslo_config import cfg
from oslo_utils import importutils
from oslo_utils import netutils
from oslo_utils import strutils
from oslo_utils import uuidutils

from ironic.common import exception
from ironic.common.i18n import _
from ironic.common import keystone
from ironic.conf import json_rpc


CONF = cfg.CONF
LOG = logging.getLogger(__name__)
_SESSION = None


def _get_session():
    global _SESSION

    if _SESSION is None:
        kwargs = {}
        auth_strategy = json_rpc.auth_strategy()
        if auth_strategy != 'keystone':
            auth_type = 'none' if auth_strategy == 'noauth' else auth_strategy
            CONF.set_default('auth_type', auth_type, group='json_rpc')

            # Deprecated, remove in W
            if auth_strategy == 'http_basic':
                if CONF.json_rpc.http_basic_username:
                    kwargs['username'] = CONF.json_rpc.http_basic_username
                if CONF.json_rpc.http_basic_password:
                    kwargs['password'] = CONF.json_rpc.http_basic_password

        auth = keystone.get_auth('json_rpc', **kwargs)

        session = keystone.get_session('json_rpc', auth=auth)
        headers = {
            'Content-Type': 'application/json'
        }

        # Adds options like connect_retries
        _SESSION = keystone.get_adapter('json_rpc', session=session,
                                        additional_headers=headers)

    return _SESSION


class Client(object):
    """JSON RPC client with ironic exception handling."""

    allowed_exception_namespaces = [
        "ironic.common.exception.",
        "ironic_inspector.utils.",
    ]

    def __init__(self, serializer, version_cap=None):
        self.serializer = serializer
        self.version_cap = version_cap

    def can_send_version(self, version):
        return _can_send_version(version, self.version_cap)

    def prepare(self, topic, version=None):
        """Prepare the client to transmit a request.

        :param topic: Topic which is being addressed. Typically this
                      is the hostname of the remote json-rpc service.
        :param version: The RPC API version to utilize.
        """

        host = topic.split('.', 1)[1]
        host, port = netutils.parse_host_port(host)
        return _CallContext(
            host, self.serializer, version=version,
            version_cap=self.version_cap,
            allowed_exception_namespaces=self.allowed_exception_namespaces,
            port=port)


class _CallContext(object):
    """Wrapper object for compatibility with oslo.messaging API."""

    def __init__(self, host, serializer, version=None, version_cap=None,
                 allowed_exception_namespaces=(), port=None):
        if not port:
            self.port = CONF.json_rpc.port
        else:
            self.port = int(port)
        self.host = host
        self.serializer = serializer
        self.version = version
        self.version_cap = version_cap
        self.allowed_exception_namespaces = allowed_exception_namespaces

    def _is_known_exception(self, class_name):
        for ns in self.allowed_exception_namespaces:
            if class_name.startswith(ns):
                return True
        return False

    def _handle_error(self, error):
        if not error:
            return

        message = error['message']
        try:
            cls = error['data']['class']
        except KeyError:
            LOG.error("Unexpected error from RPC: %s", error)
            raise exception.IronicException(
                _("Unexpected error raised by RPC"))
        else:
            if not self._is_known_exception(cls):
                # NOTE(dtantsur): protect against arbitrary code execution
                LOG.error("Unexpected error from RPC: %s", error)
                raise exception.IronicException(
                    _("Unexpected error raised by RPC"))
            raise importutils.import_object(cls, message,
                                            code=error.get('code', 500))

    def call(self, context, method, version=None, **kwargs):
        """Call conductor RPC.

        Versioned objects are automatically serialized and deserialized.

        :param context: Security context.
        :param method: Method name.
        :param version: RPC API version to use.
        :param kwargs: Keyword arguments to pass.
        :return: RPC result (if any).
        """
        return self._request(context, method, cast=False, version=version,
                             **kwargs)

    def cast(self, context, method, version=None, **kwargs):
        """Call conductor RPC asynchronously.

        Versioned objects are automatically serialized and deserialized.

        :param context: Security context.
        :param method: Method name.
        :param version: RPC API version to use.
        :param kwargs: Keyword arguments to pass.
        :return: None
        """
        return self._request(context, method, cast=True, version=version,
                             **kwargs)

    def _request(self, context, method, cast=False, version=None, **kwargs):
        """Call conductor RPC.

        Versioned objects are automatically serialized and deserialized.

        :param context: Security context.
        :param method: Method name.
        :param cast: If true, use a JSON RPC notification.
        :param version: RPC API version to use.
        :param kwargs: Keyword arguments to pass.
        :return: RPC result (if any).
        """
        params = {key: self.serializer.serialize_entity(context, value)
                  for key, value in kwargs.items()}
        params['context'] = context.to_dict()

        if version is None:
            version = self.version
        if version is not None:
            _check_version(version, self.version_cap)
            params['rpc.version'] = version

        body = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params,
        }
        if not cast:
            body['id'] = (getattr(context, 'request_id', None)
                          or uuidutils.generate_uuid())

        scheme = 'http'
        if CONF.json_rpc.client_use_ssl or CONF.json_rpc.use_ssl:
            scheme = 'https'
        url = '%s://%s:%d' % (scheme,
                              netutils.escape_ipv6(self.host),
                              self.port)
        LOG.debug("RPC %s to %s with %s", method, url,
                  strutils.mask_dict_password(body))
        try:
            result = _get_session().post(url, json=body)
        except Exception as exc:
            LOG.debug('RPC %s to %s failed with %s', method, url, exc)
            raise
        LOG.debug('RPC %s to %s returned %s', method, url,
                  strutils.mask_password(result.text or '<None>'))
        if not cast:
            result = result.json()
            self._handle_error(result.get('error'))
            result = self.serializer.deserialize_entity(context,
                                                        result['result'])
            return result


def _can_send_version(requested, version_cap):
    if requested is None or version_cap is None:
        return True

    requested_parts = [int(item) for item in requested.split('.', 1)]
    version_cap_parts = [int(item) for item in version_cap.split('.', 1)]

    if requested_parts[0] != version_cap_parts[0]:
        return False  # major version mismatch
    else:
        return requested_parts[1] <= version_cap_parts[1]


def _check_version(requested, version_cap):
    if not _can_send_version(requested, version_cap):
        raise RuntimeError(_("Cannot send RPC request: requested version "
                             "%(requested)s, maximum allowed version is "
                             "%(version_cap)s") % {'requested': requested,
                                                   'version_cap': version_cap})
