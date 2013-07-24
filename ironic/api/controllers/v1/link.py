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

from wsme import types as wtypes

from ironic.api.controllers.v1 import base


class Link(base.APIBase):
    """A link representation."""

    href = wtypes.text
    "The url of a link."

    rel = wtypes.text
    "The name of a link."

    @classmethod
    def make_link(cls, rel_name, url, resource, resource_args, bookmark=False):
        template = '%s/%s/%s' if bookmark else '%s/v1/%s/%s'
        return Link(href=(template) % (url, resource, resource_args),
                    rel=rel_name)
