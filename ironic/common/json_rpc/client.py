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
# Session cache per configuration group
_SESSIONS = {}


def _get_session(group: str = 'json_rpc'):
    """Get or create a session/adapter for a configuration group.

    :param group: Configuration group name. Defaults to 'json_rpc'.
    :returns: A keystone Adapter configured for the group.
    """
    global _SESSIONS

    if group not in _SESSIONS:
        kwargs = {}
        auth_strategy = json_rpc.auth_strategy(group)
        if auth_strategy != 'keystone':
            auth_type = 'none' if auth_strategy == 'noauth' else auth_strategy
            CONF.set_default('auth_type', auth_type, group=group)

            # Deprecated, remove in W
            group_conf = getattr(CONF, group)
            if auth_strategy == 'http_basic':
                if getattr(group_conf, 'http_basic_username', None):
                    kwargs['username'] = group_conf.http_basic_username
                if getattr(group_conf, 'http_basic_password', None):
                    kwargs['password'] = group_conf.http_basic_password

        auth = keystone.get_auth(group, **kwargs)

        session = keystone.get_session(group, auth=auth)
        headers = {
            'Content-Type': 'application/json'
        }

        # Adds options like connect_retries
        _SESSIONS[group] = keystone.get_adapter(
            group, session=session, additional_headers=headers)

    return _SESSIONS[group]


class Client(object):
    """JSON RPC client with ironic exception handling."""

    allowed_exception_namespaces = [
        "ironic.common.exception.",
    ]

    def __init__(self, serializer, version_cap=None,
                 conf_group: str = 'json_rpc'):
        self.serializer = serializer
        self.version_cap = version_cap
        self.conf_group = conf_group

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
            port=port, conf_group=self.conf_group)


class _CallContext(object):
    """Wrapper object for compatibility with oslo.messaging API."""

    def __init__(self, host, serializer, version=None, version_cap=None,
                 allowed_exception_namespaces=(), port=None,
                 conf_group: str = 'json_rpc'):
        self.conf_group = conf_group
        if not port:
            group_conf = getattr(CONF, self.conf_group)
            self.port = group_conf.port
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

    def _debug_log_rpc(self, method, url, params, body=None,
                       result_text=None, exception=None):
        """Helper to log RPC calls with optional request_id-only logging."""
        request_id = None
        if CONF.json_rpc.debug_log_request_id_only:
            request_id = params.get('context', {}).get('request_id')

        if exception:
            # Log failure
            if request_id:
                LOG.debug('RPC %s to %s with request_id %s failed with %s',
                          method, url, request_id, exception)
            else:
                LOG.debug('RPC %s to %s failed with %s', method, url,
                          exception)
        elif result_text is not None:
            # Log success response
            if request_id:
                LOG.debug('RPC %s to %s with request_id %s completed '
                          'successfully', method, url, request_id)
            else:
                LOG.debug('RPC %s to %s returned %s', method, url,
                          strutils.mask_password(result_text or '<None>'))
        else:
            # Log request
            if request_id:
                LOG.debug("RPC %s to %s with request_id %s", method, url,
                          request_id)
            else:
                LOG.debug("RPC %s to %s with %s", method, url,
                          strutils.mask_dict_password(body))

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
        group_conf = getattr(CONF, self.conf_group)
        if group_conf.client_use_ssl or group_conf.use_ssl:
            scheme = 'https'
        url = '%s://%s:%d' % (scheme,
                              netutils.escape_ipv6(self.host),
                              self.port)
        self._debug_log_rpc(method, url, params, body=body)

        try:
            result = _get_session(self.conf_group).post(url, json=body)
        except Exception as exc:
            self._debug_log_rpc(method, url, params, exception=exc)
            raise

        self._debug_log_rpc(method, url, params, result_text=result.text)
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
