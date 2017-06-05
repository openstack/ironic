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

    def __init__(self, is_public_api=False, **kwargs):
        """Initialize the RequestContext

        :param is_public_api: Specifies whether the request should be processed
            without authentication.
        :param kwargs: additional arguments passed to oslo.context.
        """
        super(RequestContext, self).__init__(**kwargs)
        self.is_public_api = is_public_api

    def to_policy_values(self):
        policy_values = super(RequestContext, self).to_policy_values()
        policy_values.update({
            'project_name': self.project_name,
            'is_public_api': self.is_public_api,
        })
        return policy_values

    @classmethod
    def from_dict(cls, values, **kwargs):
        # TODO(vdrok): these are left so that if older service communicates
        # with a new one, new one could still understand what old one sends,
        # remove in Queens
        kwargs.setdefault('is_public_api', values.get('is_public_api', False))
        if 'domain_id' in values:
            kwargs.setdefault('user_domain', values['domain_id'])
        return super(RequestContext, RequestContext).from_dict(values,
                                                               **kwargs)

    def ensure_thread_contain_context(self):
        """Ensure threading contains context

        For async/periodic tasks, the context of local thread is missing.
        Set it with request context and this is useful to log the request_id
        in log messages.

        """
        if context.get_current():
            return
        self.update_store()


def get_admin_context():
    """Create an administrator context."""

    context = RequestContext(auth_token=None,
                             tenant=None,
                             is_admin=True,
                             overwrite=False)
    return context
