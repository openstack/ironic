# -*- encoding: utf-8 -*-
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

from oslo_context import context


class RequestContext(context.RequestContext):
    """Extends security contexts from the oslo.context library."""

    # NOTE(TheJulia): This is a flag used by oslo.context which allows us to
    # pass in a list of keys to preserve when calling from_dict() on the
    # RequestContext class.
    FROM_DICT_EXTRA_KEYS = ['auth_token_info']

    def __init__(self, is_public_api=False, auth_token_info=None, **kwargs):
        """Initialize the RequestContext

        :param is_public_api: Specifies whether the request should be processed
            without authentication.
        :param auth_token_info: Parameter to house auth token validation
            response data such as the user auth token's project id as opposed
            to the bearer token used. This allows for easy access to attributes
            for the end user when actions are taken on behalf of a user.
        :param kwargs: additional arguments passed to oslo.context.
        """
        super(RequestContext, self).__init__(**kwargs)
        self.is_public_api = is_public_api
        self.auth_token_info = auth_token_info

    def to_policy_values(self):
        policy_values = super(RequestContext, self).to_policy_values()
        policy_values.update({
            'project_name': self.project_name,
            'is_public_api': self.is_public_api,
        })
        return policy_values

    def ensure_thread_contain_context(self):
        """Ensure threading contains context

        For async/periodic tasks, the context of local thread is missing.
        Set it with request context and this is useful to log the request_id
        in log messages.

        """
        if context.get_current():
            return
        self.update_store()

    @classmethod
    def from_environ(cls, environ, **kwargs):
        """Load a context object from a request environment.

        If keyword arguments are provided then they override the values in the
        request environment, injecting the kwarg arguments used by ironic, as
        unknown values are filtered out from the final context object in
        the base oslo.context library.

        :param environ: The environment dictionary associated with a request.
        :type environ: dict
        """
        context = super().from_environ(environ)
        context.is_public_api = environ.get('is_public_api', False)
        context.auth_token_info = environ.get('keystone.token_info')
        return context

    def to_dict(self):
        """Return a dictionary of context attributes."""
        # The parent class in oslo.context provides the core standard
        # fields, but does not go beyond that. This preserves auth_token_info
        # for serialization and ultimately things like RPC transport.
        cdict = super().to_dict()
        cdict['auth_token_info'] = self.auth_token_info
        return cdict


def get_admin_context():
    """Create an administrator context."""

    context = RequestContext(auth_token=None,
                             project_id=None,
                             overwrite=False)
    return context
