#!/usr/bin/env python
# vim: tabstop=4 shiftwidth=4 softtabstop=4

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

import pecan
from wsme import types as wtypes

from ironic.api.controllers.v1 import base
from ironic.api.controllers.v1 import link


class Collection(base.APIBase):

    links = [link.Link]
    "A list containing a link to retrieve the next subset of the collection"

    type = wtypes.text
    "The type of the collection"

    def _check_items(self):
        if not hasattr(self, 'items') or self.items == wtypes.Unset:
            raise AttributeError(_("Collection items are uninitialized"))

    def has_next(self, limit):
        self._check_items()
        return len(self.items) and len(self.items) == limit

    def make_links(self, limit, res_name, **kwargs):
        self._check_items()
        links = []
        if self.has_next(limit):
            q_args = ''.join(['%s=%s&' % (key, kwargs[key]) for key in kwargs])
            next_args = '?%(args)slimit=%(limit)d&marker=%(marker)s' % {
                                                'args': q_args, 'limit': limit,
                                                'marker': self.items[-1].uuid}
            links = [link.Link.make_link('next', pecan.request.host_url,
                                         res_name, next_args)
                    ]
        return links
