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

import wsme

from oslo.config import cfg

CONF = cfg.CONF


def validate_limit(limit):
    if limit and limit < 0:
        raise wsme.exc.ClientSideError(_("Limit must be positive"))

    return min(CONF.api.max_limit, limit) or CONF.api.max_limit


def validate_sort_dir(sort_dir):
    if sort_dir not in ['asc', 'desc']:
        raise wsme.exc.ClientSideError(_("Invalid sort direction: %s. "
                                         "Acceptable values are "
                                         "'asc' or 'desc'") % sort_dir)
    return sort_dir


class ValidTypes(wsme.types.UserType):
    """User type for validate that value has one of a few types."""

    def __init__(self, *types):
        self.types = types

    def validate(self, value):
        for t in self.types:
            if t is wsme.types.text and isinstance(value, wsme.types.bytes):
                value = value.decode()
            if isinstance(value, t):
                return value
        else:
            raise ValueError(
                     _("Wrong type. Expected '%(type)s', got '%(value)s'")
                     % {'type': self.types, 'value': type(value)})
