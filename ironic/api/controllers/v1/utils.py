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

import re
import wsme

from oslo.config import cfg

CONF = cfg.CONF


def validate_limit(limit):
    if limit and limit < 0:
        raise wsme.exc.ClientSideError(_("Limit must be positive"))

    return min(CONF.api_limit_max, limit) or CONF.api_limit_max


def validate_sort_dir(sort_dir):
    if sort_dir not in ['asc', 'desc']:
        raise wsme.exc.ClientSideError(_("Invalid sort direction: %s. "
                                         "Acceptable values are "
                                         "'asc' or 'desc'") % sort_dir)
    return sort_dir


def validate_patch(patch):
    """Performs a basic validation on patch."""

    if not isinstance(patch, list):
        patch = [patch]

    path_pattern = re.compile("(/[\w-]+)+$")
    for p in patch:
        if not isinstance(p, dict) or \
                any(key for key in ["path", "op"] if key not in p):
            raise wsme.exc.ClientSideError(_("Invalid patch format: %s")
                                             % str(p))

        path = p["path"]
        op = p["op"]

        if op not in ["add", "replace", "remove"]:
            raise wsme.exc.ClientSideError(_("Operation not supported: %s")
                                             % op)

        if not path_pattern.match(path):
            raise wsme.exc.ClientSideError(_("Invalid path: %s") % path)

        if op == "add":
            if path.count('/') == 1:
                raise wsme.exc.ClientSideError(_("Adding an additional "
                                                 "attribute (%s) to the "
                                                 "resource is not allowed")
                                                 % path)
        if op in ["remove", "replace", "add"]:
            if path.startswith('/uuid'):
                raise wsme.exc.ClientSideError(_("UUIDs can not be removed "
                                                 "or replaced"))


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
            raise ValueError("Wrong type. Expected '%s', got  '%s'" % (
                             self.types, type(value)))
