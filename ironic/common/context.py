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
from oslo_log import log

LOG = log.getLogger(__name__)


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
        # TODO(vdrok): remove all of these apart from is_public_api and
        # project_name after deprecation period
        policy_values.update({
            'user': self.user,
            'domain_id': self.user_domain,
            'domain_name': self.user_domain_name,
            'tenant': self.tenant,
            'project_name': self.project_name,
            'is_public_api': self.is_public_api,
        })
        return policy_values

    def to_dict(self):
        # TODO(vdrok): reuse the base class to_dict in Pike
        return {'auth_token': self.auth_token,
                'user': self.user,
                'tenant': self.tenant,
                'is_admin': self.is_admin,
                'read_only': self.read_only,
                'show_deleted': self.show_deleted,
                'request_id': self.request_id,
                'domain_id': self.user_domain,
                'roles': self.roles,
                'domain_name': self.user_domain_name,
                'is_public_api': self.is_public_api}

    @classmethod
    def from_dict(cls, values, **kwargs):
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
