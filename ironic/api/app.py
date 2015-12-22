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

from oslo_config import cfg
import oslo_middleware.cors as cors_middleware
import pecan

from ironic.api import acl
from ironic.api import config
from ironic.api.controllers.base import Version
from ironic.api import hooks
from ironic.api import middleware
from ironic.common.i18n import _

api_opts = [
    cfg.StrOpt(
        'auth_strategy',
        default='keystone',
        choices=['noauth', 'keystone'],
        help=_('Authentication strategy used by ironic-api. "noauth" should '
               'not be used in a production environment because all '
               'authentication will be disabled.')),
    cfg.BoolOpt('debug_tracebacks_in_api',
                default=False,
                help=_('Return server tracebacks in the API response for any '
                       'error responses. WARNING: this is insecure '
                       'and should not be used in a production environment.')),
    cfg.BoolOpt('pecan_debug',
                default=False,
                help=_('Enable pecan debug mode. WARNING: this is insecure '
                       'and should not be used in a production environment.')),
]

CONF = cfg.CONF
CONF.register_opts(api_opts)


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

    if pecan_config.app.enable_acl:
        app_hooks.append(hooks.TrustedCallHook())

    pecan.configuration.set_config(dict(pecan_config), overwrite=True)

    app = pecan.make_app(
        pecan_config.app.root,
        static_root=pecan_config.app.static_root,
        debug=CONF.pecan_debug,
        force_canonical=getattr(pecan_config.app, 'force_canonical', True),
        hooks=app_hooks,
        wrap_app=middleware.ParsableErrorMiddleware,
    )

    if pecan_config.app.enable_acl:
        app = acl.install(app, cfg.CONF, pecan_config.app.acl_public_routes)

    # Create a CORS wrapper, and attach ironic-specific defaults that must be
    # included in all CORS responses.
    app = cors_middleware.CORS(app, CONF)
    app.set_latent(
        allow_headers=[Version.max_string, Version.min_string, Version.string],
        allow_methods=['GET', 'PUT', 'POST', 'DELETE', 'PATCH'],
        expose_headers=[Version.max_string, Version.min_string, Version.string]
    )

    return app


class VersionSelectorApplication(object):
    def __init__(self):
        pc = get_pecan_config()
        pc.app.enable_acl = (CONF.auth_strategy == 'keystone')
        self.v1 = setup_app(pecan_config=pc)

    def __call__(self, environ, start_response):
        return self.v1(environ, start_response)
