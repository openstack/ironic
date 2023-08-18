# -*- encoding: utf-8 -*-
#
# Copyright © 2012 New Dream Network, LLC (DreamHost)
#
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

from http import client as http_client
import re

from oslo_config import cfg
from oslo_log import log
from pecan import hooks

from ironic.common import context
from ironic.common import policy
from ironic.conductor import rpcapi
from ironic.db import api as dbapi

LOG = log.getLogger(__name__)

CHECKED_DEPRECATED_POLICY_ARGS = False
INBOUND_HEADER = 'X-Openstack-Request-Id'
GLOBAL_REQ_ID = 'openstack.global_request_id'
ID_FORMAT = (r'^req-[a-f0-9]{8}-[a-f0-9]{4}-'
             r'[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$')

# Call once, don't call on each request because it is
# a ton of extra overhead.
DBAPI = dbapi.get_instance()


def policy_deprecation_check():
    global CHECKED_DEPRECATED_POLICY_ARGS
    if not CHECKED_DEPRECATED_POLICY_ARGS:
        enforcer = policy.get_enforcer()
        substitution_dict = {
            'user': 'user_id',
            'domain_id': 'user_domain_id',
            'domain_name': 'user_domain_id',
            'tenant': 'project_name',
        }
        policy_rules = enforcer.file_rules.values()
        for rule in policy_rules:
            str_rule = str(rule)
            for deprecated, replacement in substitution_dict.items():
                if re.search(r'\b%s\b' % deprecated, str_rule):
                    LOG.warning(
                        "Deprecated argument %(deprecated)s is used in policy "
                        "file rule (%(rule)s), please use %(replacement)s "
                        "argument instead. The possibility to use deprecated "
                        "arguments will be removed in the Pike release.",
                        {'deprecated': deprecated, 'replacement': replacement,
                         'rule': str_rule})
                    if deprecated == 'domain_name':
                        LOG.warning(
                            "Please note that user_domain_id is an ID of the "
                            "user domain, while the deprecated domain_name is "
                            "its name. The policy rule has to be updated "
                            "accordingly.")
        CHECKED_DEPRECATED_POLICY_ARGS = True


class ConfigHook(hooks.PecanHook):
    """Attach the config object to the request so controllers can get to it."""

    def before(self, state):
        state.request.cfg = cfg.CONF


class DBHook(hooks.PecanHook):
    """Attach the dbapi object to the request so controllers can get to it."""

    def before(self, state):
        state.request.dbapi = DBAPI

    def after(self, state):
        # Explicitly set to None since we don't need the DB connection
        # after we're done processing the request.
        state.request.dbapi = None


class ContextHook(hooks.PecanHook):
    """Configures a request context and attaches it to the request."""
    def __init__(self, public_api_routes):
        self.public_api_routes = public_api_routes
        super(ContextHook, self).__init__()

    def before(self, state):
        is_public_api = state.request.environ.get('is_public_api', False)
        auth_token_info = state.request.environ.get('keystone.token_info')
        # set the global_request_id if we have an inbound request id
        gr_id = state.request.headers.get(INBOUND_HEADER, "")
        if re.match(ID_FORMAT, gr_id):
            state.request.environ[GLOBAL_REQ_ID] = gr_id

        ctx = context.RequestContext.from_environ(
            state.request.environ,
            is_public_api=is_public_api,
            auth_token_info=auth_token_info)
        # Do not pass any token with context for noauth mode
        if cfg.CONF.auth_strategy != 'keystone':
            ctx.auth_token = None

        policy_deprecation_check()

        state.request.context = ctx

    def after(self, state):
        if state.request.context == {}:
            # An incorrect url path will not create RequestContext
            return
        # NOTE(lintan): RequestContext will generate a request_id if no one
        # passing outside, so it always contain a request_id.
        request_id = state.request.context.request_id
        state.response.headers['Openstack-Request-Id'] = request_id


class RPCHook(hooks.PecanHook):
    """Attach the rpcapi object to the request so controllers can get to it."""

    def before(self, state):
        state.request.rpcapi = rpcapi.ConductorAPI()


class NoExceptionTracebackHook(hooks.PecanHook):
    """Workaround rpc.common: deserialize_remote_exception.

    deserialize_remote_exception builds rpc exception traceback into error
    message which is then sent to the client. Such behavior is a security
    concern so this hook is aimed to cut-off traceback from the error message.

    """
    # NOTE(max_lobur): 'after' hook used instead of 'on_error' because
    # 'on_error' never fired for wsme+pecan pair. wsme @wsexpose decorator
    # catches and handles all the errors, so 'on_error' dedicated for unhandled
    # exceptions never fired.
    def after(self, state):
        # Omit empty body. Some errors may not have body at this level yet.
        if not state.response.body:
            return

        # Do nothing if there is no error.
        # Status codes in the range 200 (OK) to 399 (400 = BAD_REQUEST) are not
        # an error.
        if (http_client.OK <= state.response.status_int
                < http_client.BAD_REQUEST):
            return

        json_body = state.response.json
        # Do not remove traceback when traceback config is set
        if cfg.CONF.debug_tracebacks_in_api:
            return

        faultstring = json_body.get('faultstring')
        traceback_marker = 'Traceback (most recent call last):'
        if faultstring and traceback_marker in faultstring:
            # Cut-off traceback.
            faultstring = faultstring.split(traceback_marker, 1)[0]
            # Remove trailing newlines and spaces if any.
            json_body['faultstring'] = faultstring.rstrip()
            # Replace the whole json. Cannot change original one because it's
            # generated on the fly.
            state.response.json = json_body


class PublicUrlHook(hooks.PecanHook):
    """Attach the right public_url to the request.

    Attach the right public_url to the request so resources can create
    links even when the API service is behind a proxy or SSL terminator.

    """

    def before(self, state):
        if cfg.CONF.oslo_middleware.enable_proxy_headers_parsing:
            state.request.public_url = state.request.application_url
        else:
            state.request.public_url = (cfg.CONF.api.public_endpoint
                                        or state.request.host_url)
