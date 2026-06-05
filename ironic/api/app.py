
# Copyright © 2012 New Dream Network, LLC (DreamHost)
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

import keystonemiddleware.audit as audit_middleware
from keystonemiddleware import auth_token
from oslo_config import cfg
from oslo_log import log as logging
import oslo_middleware.cors as cors_middleware
from oslo_middleware import healthcheck
from oslo_middleware import http_proxy_to_wsgi
from oslo_middleware import request_id
import osprofiler.web as osprofiler_web
import pecan
import stevedore

from ironic.api import config
from ironic.api.controllers import base
from ironic.api import hooks
from ironic.api import middleware
from ironic.api.middleware import auth_public_routes
from ironic.api.middleware import json_depth
from ironic.api.middleware import json_ext
from ironic.api.middleware import request_log
from ironic.common import auth_basic
from ironic.common import exception
from ironic.common.i18n import _
from ironic.conf import CONF


LOG = logging.getLogger(__name__)


HTTP_RESP_HEADER_REQUEST_ID = 'openstack-request-id'


class IronicCORS(cors_middleware.CORS):
    """Ironic-specific CORS class

    We're adding the Ironic-specific version headers to the list of simple
    headers in order that a request bearing those headers might be accepted by
    the Ironic REST API.
    """
    simple_headers = cors_middleware.CORS.simple_headers + [
        'X-Auth-Token',
        base.Version.max_string,
        base.Version.min_string,
        base.Version.string
    ]


class IronicRequestId(request_id.RequestId):
    """Ironic-specific request id middleware

    Base request id middleware uses x-openstack-request-id but ironic has been
    using openstack-request-id historically. Replace the header for backward
    compatibility.
    """
    compat_headers = [HTTP_RESP_HEADER_REQUEST_ID]


def get_pecan_config():
    # Set up the pecan configuration
    filename = config.__file__.replace('.pyc', '.py')
    return pecan.configuration.conf_from_file(filename)


def setup_app(pecan_config=None, extra_hooks=None):
    app_hooks = [hooks.ConfigHook(),
                 hooks.DBHook(),
                 hooks.ContextHook(pecan_config.app.acl_public_routes),
                 hooks.RPCHook(),
                 hooks.NoExceptionTracebackHook(),
                 hooks.PublicUrlHook()]
    if extra_hooks:
        app_hooks.extend(extra_hooks)

    if not pecan_config:
        pecan_config = get_pecan_config()

    pecan.configuration.set_config(dict(pecan_config), overwrite=True)

    app = pecan.make_app(
        pecan_config.app.root,
        debug=CONF.pecan_debug,
        static_root=pecan_config.app.static_root if CONF.pecan_debug else None,
        hooks=app_hooks,
        wrap_app=middleware.ParsableErrorMiddleware,
        # NOTE(dtantsur): enabling this causes weird issues with nodes named
        # as if they had a known mime extension, e.g. "mynode.1". We do
        # simulate the same behaviour for .json extensions for backward
        # compatibility through JsonExtensionMiddleware.
        guess_content_type_from_ext=False,
    )

    # Guard against deeply-nested or oversized JSON payloads that
    # can crash the process via RecursionError in json.loads() or
    # exhaust memory.  This must run before any code path that
    # triggers JSON parsing or reads the request body.
    app = json_depth.JsonDepthMiddleware(
        app,
        max_depth=CONF.api.max_json_body_depth,
        max_body_size=CONF.api.max_json_body_size * 1024,
        max_provision_size=(
            CONF.api.max_json_body_size_provision * 1024),
        max_inspection_size=(
            CONF.api.max_json_body_size_inspection * 1024))

    if CONF.audit.enabled:
        try:
            app = audit_middleware.AuditMiddleware(
                app,
                audit_map_file=CONF.audit.audit_map_file,
                ignore_req_list=CONF.audit.ignore_req_list
            )
        except (EnvironmentError, OSError,
                audit_middleware.PycadfAuditApiConfigError) as e:
            raise exception.InputFileError(
                file_name=CONF.audit.audit_map_file,
                reason=e
            )

    auth_middleware = None
    if CONF.auth_strategy == "keystone":
        auth_middleware = auth_token.AuthProtocol(
            app, {"oslo_config_config": cfg.CONF})
    elif CONF.auth_strategy == "http_basic":
        auth_middleware = auth_basic.BasicAuthMiddleware(
            app, cfg.CONF.http_basic_auth_user_file)

    if auth_middleware:
        app = auth_public_routes.AuthPublicRoutes(
            app,
            auth=auth_middleware,
            public_api_routes=pecan_config.app.acl_public_routes)

    if CONF.profiler.enabled:
        app = osprofiler_web.WsgiMiddleware(app)

    # NOTE(pas-ha) this registers oslo_middleware.enable_proxy_headers_parsing
    # option, when disabled (default) this is noop middleware
    app = http_proxy_to_wsgi.HTTPProxyToWSGI(app, CONF)

    # add in the healthcheck middleware if enabled
    # NOTE(jroll) this is after the auth token middleware as we don't want auth
    # in front of this, and WSGI works from the outside in. Requests to
    # /healthcheck will be handled and returned before the auth middleware
    # is reached.
    # oslo_middleware.healthcheck.Healthcheck responds to every request it
    # sees, so route only /healthcheck to it and let all other paths fall
    # through to the API app. (LP#2151134)
    if CONF.healthcheck.enabled:
        main_app = app
        hc_app = healthcheck.Healthcheck(app, CONF)

        def app(environ, start_response):
            path = environ.get('PATH_INFO', '') or '/'
            if path == '/healthcheck' or path.startswith('/healthcheck/'):
                return hc_app(environ, start_response)
            return main_app(environ, start_response)

    app = IronicRequestId(app, CONF)

    # Create a CORS wrapper, and attach ironic-specific defaults that must be
    # included in all CORS responses.
    app = IronicCORS(app, CONF)
    cors_middleware.set_defaults(
        allow_methods=['GET', 'PUT', 'POST', 'DELETE', 'PATCH'],
        expose_headers=[base.Version.max_string, base.Version.min_string,
                        base.Version.string]
    )

    app = json_ext.JsonExtensionMiddleware(app)

    # Add request logging middleware
    app = request_log.RequestLogMiddleware(app)

    # Load custom middleware via entry points
    # Middleware are loaded in the order specified in [api] middleware config
    # and wrap the application from inside out (last in config = outermost)
    if CONF.api.middleware:
        app = _load_custom_middleware(app, CONF.api.middleware)

    return app


def _missing_middleware_callback(names):
    """Raise RuntimeError with list of missing middleware."""
    error = _('The following middleware failed to load: %s')
    raise RuntimeError(error % ', '.join(names))


def _load_custom_middleware(app, middleware_names):
    """Load custom WSGI middleware via stevedore entry points.

    :param app: The WSGI application to wrap
    :param middleware_names: List of middleware names to load
    :returns: The wrapped WSGI application
    """
    LOG.info('Loading custom API middleware: %s', middleware_names)
    mgr = stevedore.NamedExtensionManager(
        'ironic.api.middleware',
        names=middleware_names,
        invoke_on_load=False,
        on_missing_entrypoints_callback=_missing_middleware_callback,
        name_order=True,
    )
    for ext in mgr:
        LOG.info('Applying middleware: %s (%s)', ext.name, ext.plugin)
        app = ext.plugin(app)
    return app


class VersionSelectorApplication(object):
    def __init__(self):
        pc = get_pecan_config()
        self.v1 = setup_app(pecan_config=pc)

    def __call__(self, environ, start_response):
        return self.v1(environ, start_response)
