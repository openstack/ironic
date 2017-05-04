#    Copyright (c) 2015 Intel Corporation
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
"""
Tests for the versions constants and methods.
"""

import re

from ironic.api.controllers.v1 import versions
from ironic.tests import base


class TestVersionConstants(base.TestCase):

    def setUp(self):
        super(TestVersionConstants, self).setUp()

        # Get all of our named constants.  They all begin with r'MINOR_[0-9]'
        self.minor_consts = [x for x in dir(versions)
                             if re.search(r'^MINOR_[0-9]', x)]

        # Sort key needs to be an integer
        def minor_key(x):
            return int(x.split('_', 2)[1])
        self.minor_consts.sort(key=minor_key)

    def test_max_ver_str(self):
        # Test to make sure MAX_VERSION_STRING corresponds with the largest
        # MINOR_ constant

        max_ver = '1.{}'.format(getattr(versions, self.minor_consts[-1]))
        self.assertEqual(max_ver, versions.MAX_VERSION_STRING)

    def test_min_ver_str(self):
        # Try to make sure someone doesn't change the MIN_VERSION_STRING by
        # accident and make sure it exists
        self.assertEqual('1.1', versions.MIN_VERSION_STRING)

    def test_name_value_match(self):
        # Test to make sure variable name matches the value.  For example
        # MINOR_99_FOO should equal 99

        for var_name in self.minor_consts:
            version = int(var_name.split('_', 2)[1])
            self.assertEqual(
                version, getattr(versions, var_name),
                'Constant "{}" does not equal {}'.format(var_name, version))

    def test_duplicates(self):
        # Test to make sure no duplicates values

        seen_values = set()
        for var_name in self.minor_consts:
            value = getattr(versions, var_name)
            self.assertNotIn(
                value, seen_values,
                'The value {} has been used more than once'.format(value))
            seen_values.add(value)
