# Copyright 2013 Red Hat, Inc.
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

from wsme import types as wtypes

from ironic import api
from ironic.api.controllers import base
from ironic.api.controllers import link


class Collection(base.APIBase):

    next = str
    """A link to retrieve the next subset of the collection"""

    @property
    def collection(self):
        return getattr(self, self._type)

    @classmethod
    def get_key_field(cls):
        return 'uuid'

    def has_next(self, limit):
        """Return whether collection has more items."""
        return len(self.collection) and len(self.collection) == limit

    def get_next(self, limit, url=None, **kwargs):
        """Return a link to the next subset of the collection."""
        if not self.has_next(limit):
            return wtypes.Unset

        resource_url = url or self._type
        fields = kwargs.pop('fields', None)
        # NOTE(saga): If fields argument is present in kwargs and not None. It
        # is a list so convert it into a comma seperated string.
        if fields:
            kwargs['fields'] = ','.join(fields)
        q_args = ''.join(['%s=%s&' % (key, kwargs[key]) for key in kwargs])
        next_args = '?%(args)slimit=%(limit)d&marker=%(marker)s' % {
            'args': q_args, 'limit': limit,
            'marker': getattr(self.collection[-1], self.get_key_field())}

        return link.Link.make_link('next', api.request.public_url,
                                   resource_url, next_args).href
