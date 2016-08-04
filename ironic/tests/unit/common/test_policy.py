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

from oslo_policy import policy as oslo_policy

from ironic.common import exception
from ironic.common import policy
from ironic.tests import base


class PolicyInCodeTestCase(base.TestCase):
    """Tests whether the configuration of the policy engine is corect."""

    def test_admin_api(self):
        creds = ({'roles': ['admin']},
                 {'roles': ['administrator']},
                 {'roles': ['admin', 'administrator']})

        for c in creds:
            self.assertTrue(policy.check('admin_api', c, c))

    def test_public_api(self):
        creds = {'is_public_api': 'True'}
        self.assertTrue(policy.check('public_api', creds, creds))

    def test_show_password(self):
        creds = {'roles': [u'admin'], 'tenant': 'admin'}
        self.assertTrue(policy.check('show_password', creds, creds))

    def test_node_get(self):
        creds = {'roles': ['baremetal_observer'], 'tenant': 'demo'}
        self.assertTrue(policy.check('baremetal:node:get', creds, creds))

    def test_node_create(self):
        creds = {'roles': ['baremetal_admin'], 'tenant': 'demo'}
        self.assertTrue(policy.check('baremetal:node:create', creds, creds))


class PolicyInCodeTestCaseNegative(base.TestCase):
    """Tests whether the configuration of the policy engine is corect."""

    def test_admin_api(self):
        creds = {'roles': ['Member']}
        self.assertFalse(policy.check('admin_api', creds, creds))

    def test_public_api(self):
        creds = ({'is_public_api': 'False'}, {})

        for c in creds:
            self.assertFalse(policy.check('public_api', c, c))

    def test_show_password(self):
        creds = {'roles': [u'admin'], 'tenant': 'demo'}
        self.assertFalse(policy.check('show_password', creds, creds))

    def test_node_get(self):
        creds = {'roles': ['generic_user'], 'tenant': 'demo'}
        self.assertFalse(policy.check('baremetal:node:get', creds, creds))

    def test_node_create(self):
        creds = {'roles': ['baremetal_observer'], 'tenant': 'demo'}
        self.assertFalse(policy.check('baremetal:node:create', creds, creds))


class PolicyTestCase(base.TestCase):
    """Tests whether ironic.common.policy behaves as expected."""

    def setUp(self):
        super(PolicyTestCase, self).setUp()
        rule = oslo_policy.RuleDefault('has_foo_role', "role:foo")
        enforcer = policy.get_enforcer()
        enforcer.register_default(rule)

    def test_authorize_passes(self):
        creds = {'roles': ['foo']}
        policy.authorize('has_foo_role', creds, creds)

    def test_authorize_access_forbidden(self):
        creds = {'roles': ['bar']}
        self.assertRaises(
            exception.HTTPForbidden,
            policy.authorize, 'has_foo_role', creds, creds)

    def test_authorize_policy_not_registered(self):
        creds = {'roles': ['foo']}
        self.assertRaises(
            oslo_policy.PolicyNotRegistered,
            policy.authorize, 'has_bar_role', creds, creds)

    def test_enforce_existing_rule_passes(self):
        creds = {'roles': ['foo']}
        self.assertTrue(policy.enforce('has_foo_role', creds, creds))

    def test_enforce_missing_rule_fails(self):
        creds = {'roles': ['foo']}
        self.assertFalse(policy.enforce('has_bar_role', creds, creds))

    def test_enforce_existing_rule_fails(self):
        creds = {'roles': ['bar']}
        self.assertFalse(policy.enforce('has_foo_role', creds, creds))

    def test_enforce_existing_rule_raises(self):
        creds = {'roles': ['bar']}
        self.assertRaises(
            exception.IronicException,
            policy.enforce, 'has_foo_role', creds, creds, True,
            exception.IronicException)
