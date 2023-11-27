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

import sys
from unittest import mock

import ddt
from oslo_config import cfg
from oslo_policy import policy as oslo_policy

from ironic.common import exception
from ironic.common import policy
from ironic.tests import base


@ddt.ddt
class PolicyInCodeTestCase(base.TestCase):
    """Tests whether the configuration of the policy engine is correct."""

    @ddt.data(
        dict(
            rule='admin_api',
            check=True,
            targets=[],
            creds=[
                {'roles': ['admin']},
                {'roles': ['administrator']},
                {'roles': ['admin', 'administrator']}
            ]),
        dict(
            rule='admin_api',
            check=False,
            targets=[],
            creds=[{'roles': ['Member']}]),
        dict(
            rule='public_api',
            check=True,
            targets=[],
            creds=[{'is_public_api': 'True'}]),
        dict(
            rule='public_api',
            check=False,
            targets=[],
            creds=[
                {'is_public_api': 'False'},
                {}
            ]),
        dict(
            rule='show_password',
            check=False,
            targets=[],
            creds=[{
                'roles': ['admin'],
                'project_name': 'admin',
                'project_domain_id': 'default'
            }, {
                'roles': ['admin'],
                'tenant': 'demo'
            }]),
        dict(
            rule='is_member',
            check=True,
            targets=[],
            creds=[
                {'project_name': 'demo', 'project_domain_id': 'default'},
                {'project_name': 'baremetal',
                 'project_domain_id': 'default'},
                {'project_name': 'demo', 'project_domain_id': None},
                {'project_name': 'baremetal', 'project_domain_id': None}
            ]),
        dict(
            rule='is_member',
            check=False,
            targets=[],
            creds=[{'project_name': 'demo1',
                    'project_domain_id': 'default2'}]),
        dict(
            rule='is_node_owner',
            check=True,
            targets=[{
                'node.owner': '1234',
                'project_id': '1234',
                'project_name': 'demo',
                'project_domain_id': 'default'
            }],
            creds=[{
                'project_id': '1234',
                'project_name': 'demo',
                'project_domain_id': 'default'
            }]),
        dict(
            rule='is_node_owner',
            check=False,
            targets=[{
                'node.owner': '1234',
                'project_id': '1234',
                'project_name': 'demo',
                'project_domain_id': 'default'
            }],
            creds=[{
                'project_id': '5678',
                'project_name': 'demo',
                'project_domain_id': 'default'
            }]),
        dict(
            rule='is_node_lessee',
            check=True,
            targets=[{
                'node.lessee': '1234',
                'project_id': '1234',
                'project_name': 'demo',
                'project_domain_id': 'default'
            }],
            creds=[{
                'project_id': '1234',
                'project_name': 'demo',
                'project_domain_id': 'default'
            }]),
        dict(
            rule='is_node_lessee',
            check=False,
            targets=[{
                'node.lessee': '1234',
                'project_id': '1234',
                'project_name': 'demo',
                'project_domain_id': 'default'
            }],
            creds=[{
                'project_id': '5678',
                'project_name': 'demo',
                'project_domain_id': 'default'
            }]),
        dict(
            rule='is_allocation_owner',
            check=True,
            targets=[{
                'allocation.owner': '1234',
                'project_id': '1234',
                'project_name': 'demo',
                'project_domain_id': 'default'
            }],
            creds=[{
                'project_id': '1234',
                'project_name': 'demo',
                'project_domain_id': 'default'
            }]),
        dict(
            rule='is_allocation_owner',
            check=False,
            targets=[{
                'allocation.owner': '1234',
                'project_id': '1234',
                'project_name': 'demo',
                'project_domain_id': 'default'
            }],
            creds=[{
                'project_id': '5678',
                'project_name': 'demo',
                'project_domain_id': 'default'
            }]),
        dict(
            rule='baremetal:node:get',
            check=False,
            targets=[],
            creds=[{
                'roles': ['baremetal_observer'],
                'project_name': 'demo',
                'project_domain_id': 'default'
            }]),
        dict(
            rule='baremetal:node:get',
            check=False,
            targets=[],
            creds=[{'roles': ['generic_user'], 'tenant': 'demo'}]),
        dict(
            rule='baremetal:node:create',
            check=False,
            targets=[],
            creds=[{
                'roles': ['baremetal_admin'],
                'project_name': 'demo',
                'project_domain_id': 'default'
            }]),
        dict(
            rule='baremetal:node:create',
            check=False,
            targets=[],
            creds=[{
                'roles': ['baremetal_observer'],
                'tenant': 'demo'
            }]),
    )
    @ddt.unpack
    def test_creds(self, rule, check, targets, creds):
        if not targets:
            # when targets are not specified in the scenario,
            # use the creds as the target dict
            targets = creds

        for target, creds in zip(targets, creds):
            result = policy.check(rule, target, creds)

            if result != check:
                msg = '%s should be %s for target %s, creds %s' % (
                    rule, check, target, creds)
                if check:
                    self.assertTrue(result, msg)
                else:
                    self.assertFalse(result, msg)


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

    @mock.patch.object(cfg, 'CONF', autospec=True)
    @mock.patch.object(policy, 'get_enforcer', autospec=True)
    def test_get_oslo_policy_enforcer_no_args(self, mock_gpe, mock_cfg):
        mock_gpe.return_value = mock.Mock()
        args = []
        with mock.patch.object(sys, 'argv', args):
            policy.get_oslo_policy_enforcer()
        mock_cfg.assert_called_once_with([], project='ironic')
        self.assertEqual(1, mock_gpe.call_count)

    @mock.patch.object(cfg, 'CONF', autospec=True)
    @mock.patch.object(policy, 'get_enforcer', autospec=True)
    def test_get_oslo_policy_enforcer_namespace(self, mock_gpe, mock_cfg):
        mock_gpe.return_value = mock.Mock()
        args = ['opg', '--namespace', 'ironic']
        with mock.patch.object(sys, 'argv', args):
            policy.get_oslo_policy_enforcer()
        mock_cfg.assert_called_once_with([], project='ironic')
        self.assertEqual(1, mock_gpe.call_count)

    @mock.patch.object(cfg, 'CONF', autospec=True)
    @mock.patch.object(policy, 'get_enforcer', autospec=True)
    def test_get_oslo_policy_enforcer_config_file(self, mock_gpe, mock_cfg):
        mock_gpe.return_value = mock.Mock()
        args = ['opg', '--namespace', 'ironic', '--config-file', 'my.cfg']
        with mock.patch.object(sys, 'argv', args):
            policy.get_oslo_policy_enforcer()
        mock_cfg.assert_called_once_with(['--config-file', 'my.cfg'],
                                         project='ironic')
        self.assertEqual(1, mock_gpe.call_count)
