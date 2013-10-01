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

import six
import wsme

from ironic.api.controllers.v1 import utils
from ironic.tests.api import base

from oslo.config import cfg

CONF = cfg.CONF


class TestApiUtils(base.FunctionalTest):

    def test_validate_limit(self):
        limit = utils.validate_limit(10)
        self.assertEqual(10, 10)

        # max limit
        limit = utils.validate_limit(999999999)
        self.assertEqual(limit, CONF.api_limit_max)

        # negative
        self.assertRaises(wsme.exc.ClientSideError, utils.validate_limit, -1)

    def test_validate_sort_dir(self):
        sort_dir = utils.validate_sort_dir('asc')
        self.assertEqual('asc', sort_dir)

        # invalid sort_dir parameter
        self.assertRaises(wsme.exc.ClientSideError,
                          utils.validate_sort_dir,
                          'fake-sort')

    def test_validate_patch(self):
        patch = [{'op': 'remove', 'value': 'bar', 'path': '/foo'}]
        utils.validate_patch(patch)

        patch = [{'op': 'add', 'value': 'bar', 'path': '/extra/foo'}]
        utils.validate_patch(patch)

        patch = [{'op': 'replace', 'value': 'bar', 'path': '/foo'}]
        utils.validate_patch(patch)

    def test_validate_patch_wrong_format(self):
        # missing path
        patch = [{'op': 'remove'}]
        self.assertRaises(wsme.exc.ClientSideError,
                          utils.validate_patch,
                          patch)
        # wrong op
        patch = [{'op': 'foo', 'value': 'bar', 'path': '/foo'}]
        self.assertRaises(wsme.exc.ClientSideError,
                          utils.validate_patch,
                          patch)

    def test_validate_patch_wrong_path(self):
        # non-alphanumeric characters
        patch = [{'path': '/fo^o', 'op': 'remove'}]
        self.assertRaises(wsme.exc.ClientSideError,
                          utils.validate_patch,
                          patch)
        # empty path
        patch = [{'path': '', 'op': 'remove'}]
        self.assertRaises(wsme.exc.ClientSideError,
                          utils.validate_patch,
                          patch)

        patch = [{'path': '/', 'op': 'remove'}]
        self.assertRaises(wsme.exc.ClientSideError,
                          utils.validate_patch,
                          patch)

    def test_validate_patch_uuid(self):
        patch = [{'op': 'remove', 'path': '/uuid'}]
        self.assertRaises(wsme.exc.ClientSideError,
                          utils.validate_patch,
                          patch)

        patch = [{'op': 'replace',
                  'value': '105f5cd9-ae67-480a-8c10-62040213b8fd',
                  'path': '/uuid'}]
        self.assertRaises(wsme.exc.ClientSideError,
                          utils.validate_patch,
                          patch)

        patch = [{'op': 'add',
                  'value': '105f5cd9-ae67-480a-8c10-62040213b8fd',
                  'path': '/uuid'}]
        self.assertRaises(wsme.exc.ClientSideError,
                          utils.validate_patch,
                          patch)

    def test_valid_types(self):
        vt = utils.ValidTypes(wsme.types.text, six.integer_types)

        value = vt.validate("hello")
        self.assertEqual("hello", value)

        value = vt.validate(10)
        self.assertEqual(10, value)

        # wrong value
        self.assertRaises(ValueError, vt.validate, 0.10)
