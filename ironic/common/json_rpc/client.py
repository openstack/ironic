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

import base64

from oslo_config import cfg
from oslo_log import log
from oslo_utils import importutils
from oslo_utils import strutils
from oslo_utils import uuidutils

from ironic.common import exception
from ironic.common.i18n import _
from ironic.common import json_rpc
from ironic.common import keystone


CONF = cfg.CONF
LOG = log.getLogger(__name__)
_SESSION = None


def _get_session():
    global _SESSION

    if _SESSION is None:
        auth_strategy = json_rpc.auth_strategy()
        if auth_strategy == 'keystone':
            auth = keystone.get_auth('json_rpc')
        else:
            auth = None

        session = keystone.get_session('json_rpc', auth=auth)
        headers = {
            'Content-Type': 'application/json'
        }
        if auth_strategy == 'http_basic':
            token = '{}:{}'.format(
                CONF.json_rpc.http_basic_username,
                CONF.json_rpc.http_basic_password
            ).encode('utf-8')
            encoded = base64.b64encode(token).decode('utf-8')
            headers['Authorization'] = 'Basic {}'.format(encoded)

        # Adds options like connect_retries
        _SESSION = keystone.get_adapter('json_rpc', session=session,
                                        additional_headers=headers)

    return _SESSION


class Client(object):
    """JSON RPC client with ironic exception handling."""

    def __init__(self, serializer, version_cap=None):
        self.serializer = serializer
        self.version_cap = version_cap

    def can_send_version(self, version):
        return _can_send_version(version, self.version_cap)

    def prepare(self, topic, version=None):
        host = topic.split('.', 1)[1]
        return _CallContext(host, self.serializer, version=version,
                            version_cap=self.version_cap)


class _CallContext(object):
    """Wrapper object for compatibility with oslo.messaging API."""

    def __init__(self, host, serializer, version=None, version_cap=None):
        self.host = host
        self.serializer = serializer
        self.version = version
        self.version_cap = version_cap

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
            if not cls.startswith('ironic.common.exception.'):
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
            body['id'] = context.request_id or uuidutils.generate_uuid()

        LOG.debug("RPC %s with %s", method, strutils.mask_dict_password(body))
        url = 'http://%s:%d' % (self.host, CONF.json_rpc.port)
        result = _get_session().post(url, json=body)
        LOG.debug('RPC %s returned %s', method,
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
