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

"""Implementation of JSON RPC for communication between API and conductors.

This module implementa a subset of JSON RPC 2.0 as defined in
https://www.jsonrpc.org/specification. Main differences:
* No support for batched requests.
* No support for positional arguments passing.
* No JSON RPC 1.0 fallback.
"""

import json

from keystonemiddleware import auth_token
from oslo_config import cfg
from oslo_log import log
import oslo_messaging
from oslo_service import service
from oslo_service import wsgi
from oslo_utils import strutils
import webob

from ironic.common import context as ir_context
from ironic.common import exception
from ironic.common.i18n import _
from ironic.common import json_rpc


CONF = cfg.CONF
LOG = log.getLogger(__name__)
_BLACK_LIST = {'init_host', 'del_host', 'target', 'iter_nodes'}


def _build_method_map(manager):
    """Build mapping from method names to their bodies.

    :param manager: A conductor manager.
    :return: dict with mapping
    """
    result = {}
    for method in dir(manager):
        if method.startswith('_') or method in _BLACK_LIST:
            continue
        func = getattr(manager, method)
        if not callable(func):
            continue
        LOG.debug('Adding RPC method %s', method)
        result[method] = func
    return result


class JsonRpcError(exception.IronicException):
    pass


class ParseError(JsonRpcError):
    code = -32700
    _msg_fmt = _("Invalid JSON received by RPC server")


class InvalidRequest(JsonRpcError):
    code = -32600
    _msg_fmt = _("Invalid request object received by RPC server")


class MethodNotFound(JsonRpcError):
    code = -32601
    _msg_fmt = _("Method %(name)s was not found")


class InvalidParams(JsonRpcError):
    code = -32602
    _msg_fmt = _("Params %(params)s are invalid for %(method)s: %(error)s")


class WSGIService(service.Service):
    """Provides ability to launch JSON RPC as a WSGI application."""

    def __init__(self, manager, serializer):
        self.manager = manager
        self.serializer = serializer
        self._method_map = _build_method_map(manager)
        if json_rpc.require_authentication():
            conf = dict(CONF.keystone_authtoken)
            app = auth_token.AuthProtocol(self._application, conf)
        else:
            app = self._application
        self.server = wsgi.Server(CONF, 'ironic-json-rpc', app,
                                  host=CONF.json_rpc.host_ip,
                                  port=CONF.json_rpc.port,
                                  use_ssl=CONF.json_rpc.use_ssl)

    def _application(self, environment, start_response):
        """WSGI application for conductor JSON RPC."""
        request = webob.Request(environment)
        if request.method != 'POST':
            body = {'error': {'code': 405,
                              'message': _('Only POST method can be used')}}
            return webob.Response(status_code=405, json_body=body)(
                environment, start_response)

        if json_rpc.require_authentication():
            roles = (request.headers.get('X-Roles') or '').split(',')
            if 'admin' not in roles:
                LOG.debug('Roles %s do not contain "admin", rejecting '
                          'request', roles)
                body = {'error': {'code': 403, 'message': _('Forbidden')}}
                return webob.Response(status_code=403, json_body=body)(
                    environment, start_response)

        result = self._call(request)
        if result is not None:
            response = webob.Response(content_type='application/json',
                                      charset='UTF-8',
                                      json_body=result)
        else:
            response = webob.Response(status_code=204)
        return response(environment, start_response)

    def _handle_error(self, exc, request_id=None):
        """Generate a JSON RPC 2.0 error body.

        :param exc: Exception object.
        :param request_id: ID of the request (if any).
        :return: dict with response body
        """
        if isinstance(exc, oslo_messaging.ExpectedException):
            exc = exc.exc_info[1]

        expected = isinstance(exc, exception.IronicException)
        cls = exc.__class__
        if expected:
            LOG.debug('RPC error %s: %s', cls.__name__, exc)
        else:
            LOG.exception('Unexpected RPC exception %s', cls.__name__)

        response = {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {
                "code": getattr(exc, 'code', 500),
                "message": str(exc),
            }
        }
        if expected and not isinstance(exc, JsonRpcError):
            # Allow de-serializing the correct class for expected errors.
            response['error']['data'] = {
                'class': '%s.%s' % (cls.__module__, cls.__name__)
            }
        return response

    def _call(self, request):
        """Process a JSON RPC request.

        :param request: ``webob.Request`` object.
        :return: dict with response body.
        """
        request_id = None
        try:
            try:
                body = json.loads(request.text)
            except ValueError:
                LOG.error('Cannot parse JSON RPC request as JSON')
                raise ParseError()

            if not isinstance(body, dict):
                LOG.error('JSON RPC request %s is not an object (batched '
                          'requests are not supported)', body)
                raise InvalidRequest()

            request_id = body.get('id')
            params = body.get('params', {})

            if (body.get('jsonrpc') != '2.0'
                    or not body.get('method')
                    or not isinstance(params, dict)):
                LOG.error('JSON RPC request %s is invalid', body)
                raise InvalidRequest()
        except Exception as exc:
            # We do not treat malformed requests as notifications and return
            # a response even when request_id is None. This seems in agreement
            # with the examples in the specification.
            return self._handle_error(exc, request_id)

        try:
            method = body['method']
            try:
                func = self._method_map[method]
            except KeyError:
                raise MethodNotFound(name=method)

            result = self._handle_requests(func, method, params)
            if request_id is not None:
                return {
                    "jsonrpc": "2.0",
                    "result": result,
                    "id": request_id
                }
        except Exception as exc:
            result = self._handle_error(exc, request_id)
            # We treat correctly formed requests without "id" as notifications
            # and do not return any errors.
            if request_id is not None:
                return result

    def _handle_requests(self, func, name, params):
        """Convert arguments and call a method.

        :param func: Callable object.
        :param name: RPC call name for logging.
        :param params: Keyword arguments.
        :return: call result as JSON.
        """
        # TODO(dtantsur): server-side version check?
        params.pop('rpc.version', None)
        logged_params = strutils.mask_dict_password(params)

        try:
            context = params.pop('context')
        except KeyError:
            context = None
        else:
            # A valid context is required for deserialization
            if not isinstance(context, dict):
                raise InvalidParams(
                    _("Context must be a dictionary, if provided"))

            context = ir_context.RequestContext.from_dict(context)
            params = {key: self.serializer.deserialize_entity(context, value)
                      for key, value in params.items()}
            params['context'] = context

        LOG.debug('RPC %s with %s', name, logged_params)
        try:
            result = func(**params)
        # FIXME(dtantsur): we could use the inspect module, but
        # oslo_messaging.expected_exceptions messes up signatures.
        except TypeError as exc:
            raise InvalidParams(params=', '.join(params),
                                method=name, error=exc)

        if context is not None:
            # Currently it seems that we can serialize even with invalid
            # context, but I'm not sure it's guaranteed to be the case.
            result = self.serializer.serialize_entity(context, result)
        LOG.debug('RPC %s returned %s', name,
                  strutils.mask_dict_password(result)
                  if isinstance(result, dict) else result)
        return result

    def start(self):
        """Start serving this service using loaded configuration.

        :returns: None
        """
        self.server.start()

    def stop(self):
        """Stop serving this API.

        :returns: None
        """
        self.server.stop()

    def wait(self):
        """Wait for the service to stop serving this API.

        :returns: None
        """
        self.server.wait()

    def reset(self):
        """Reset server greenpool size to default.

        :returns: None
        """
        self.server.reset()
