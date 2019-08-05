# -*- encoding: utf-8 -*-

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
from oslo_config import cfg
import oslo_middleware.cors as cors_middleware
from oslo_middleware import healthcheck
from oslo_middleware import http_proxy_to_wsgi
import osprofiler.web as osprofiler_web
import pecan

from ironic.api import config
from ironic.api.controllers import base
from ironic.api import hooks
from ironic.api import middleware
from ironic.api.middleware import auth_token
from ironic.api.middleware import json_ext
from ironic.common import exception
from ironic.conf import CONF


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
        force_canonical=getattr(pecan_config.app, 'force_canonical', True),
        hooks=app_hooks,
        wrap_app=middleware.ParsableErrorMiddleware,
        # NOTE(dtantsur): enabling this causes weird issues with nodes named
        # as if they had a known mime extension, e.g. "mynode.1". We do
        # simulate the same behaviour for .json extensions for backward
        # compatibility through JsonExtensionMiddleware.
        guess_content_type_from_ext=False,
    )

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

    if CONF.auth_strategy == "keystone":
        app = auth_token.AuthTokenMiddleware(
            app, {"oslo_config_config": cfg.CONF},
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
    if CONF.healthcheck.enabled:
        app = healthcheck.Healthcheck(app, CONF)

    # Create a CORS wrapper, and attach ironic-specific defaults that must be
    # included in all CORS responses.
    app = IronicCORS(app, CONF)
    cors_middleware.set_defaults(
        allow_methods=['GET', 'PUT', 'POST', 'DELETE', 'PATCH'],
        expose_headers=[base.Version.max_string, base.Version.min_string,
                        base.Version.string]
    )

    app = json_ext.JsonExtensionMiddleware(app)

    return app


class VersionSelectorApplication(object):
    def __init__(self):
        pc = get_pecan_config()
        self.v1 = setup_app(pecan_config=pc)

    def __call__(self, environ, start_response):
        return self.v1(environ, start_response)
