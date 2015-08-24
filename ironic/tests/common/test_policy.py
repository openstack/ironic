# -*- encoding: utf-8 -*-
#
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

from ironic.common import policy
from ironic.tests import base


class PolicyTestCase(base.TestCase):
    """Tests whether the configuration of the policy engine is corect."""

    def test_admin_api(self):
        creds = ({'roles': [u'admin']},
                 {'roles': ['administrator']},
                 {'roles': ['admin', 'administrator']})

        for c in creds:
            self.assertTrue(policy.enforce('admin_api', c, c))

    def test_public_api(self):
        creds = {'is_public_api': 'True'}
        self.assertTrue(policy.enforce('public_api', creds, creds))

    def test_trusted_call(self):
        creds = ({'roles': ['admin']},
                 {'is_public_api': 'True'},
                 {'roles': ['admin'], 'is_public_api': 'True'},
                 {'roles': ['Member'], 'is_public_api': 'True'})

        for c in creds:
            self.assertTrue(policy.enforce('trusted_call', c, c))

    def test_show_password(self):
        creds = {'roles': [u'admin'], 'tenant': 'admin'}
        self.assertTrue(policy.enforce('show_password', creds, creds))


class PolicyTestCaseNegative(base.TestCase):
    """Tests whether the configuration of the policy engine is corect."""

    def test_admin_api(self):
        creds = {'roles': ['Member']}
        self.assertFalse(policy.enforce('admin_api', creds, creds))

    def test_public_api(self):
        creds = ({'is_public_api': 'False'}, {})

        for c in creds:
            self.assertFalse(policy.enforce('public_api', c, c))

    def test_trusted_call(self):
        creds = ({'roles': ['Member']},
                 {'is_public_api': 'False'},
                 {'roles': ['Member'], 'is_public_api': 'False'})

        for c in creds:
            self.assertFalse(policy.enforce('trusted_call', c, c))

    def test_show_password(self):
        creds = {'roles': [u'admin'], 'tenant': 'demo'}
        self.assertFalse(policy.enforce('show_password', creds, creds))
