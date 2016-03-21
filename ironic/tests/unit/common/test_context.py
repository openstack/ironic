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

import mock
from oslo_context import context as oslo_context

from ironic.common import context
from ironic.tests import base as tests_base


class RequestContextTestCase(tests_base.TestCase):
    def setUp(self):
        super(RequestContextTestCase, self).setUp()
        self.context_dict = {
            'auth_token': 'auth_token1',
            "user": "user1",
            "tenant": "tenant1",
            "project_name": "somename",
            'is_admin': True,
            'read_only': True,
            'show_deleted': True,
            'request_id': 'id1',
            "is_public_api": True,
            "domain": "domain_id2",
            "user_domain": "domain_id3",
            "user_domain_name": "TreeDomain",
            "project_domain": "domain_id4",
            "roles": None,
            "overwrite": True
        }

    @mock.patch.object(oslo_context.RequestContext, "__init__")
    def test_create_context(self, context_mock):
        test_context = context.RequestContext()
        context_mock.assert_called_once_with()
        self.assertFalse(test_context.is_public_api)

    def test_to_dict(self):
        ctx = context.RequestContext(**self.context_dict)
        ctx_dict = ctx.to_dict()
        self.assertEqual('auth_token1', ctx_dict['auth_token'])
        self.assertEqual('user1', ctx_dict['user'])
        self.assertEqual('tenant1', ctx_dict['tenant'])
        self.assertTrue(ctx_dict['is_admin'])
        self.assertTrue(ctx_dict['read_only'])
        self.assertTrue(ctx_dict['show_deleted'])
        self.assertEqual('id1', ctx_dict['request_id'])
        self.assertTrue(ctx_dict['is_public_api'])
        self.assertEqual('domain_id3', ctx_dict['domain_id'])
        self.assertEqual('TreeDomain', ctx_dict['domain_name'])
        self.assertEqual([], ctx_dict['roles'])
        self.assertNotIn('overwrite', ctx_dict)

    def test_from_dict(self):
        test_context = context.RequestContext.from_dict(
            {'project_name': 'demo', 'is_public_api': True,
             'domain_id': 'meow'})
        self.assertEqual('demo', test_context.project_name)
        self.assertEqual('meow', test_context.user_domain)
        self.assertTrue(test_context.is_public_api)

    def test_to_policy_values(self):
        ctx = context.RequestContext(**self.context_dict)
        ctx_dict = ctx.to_policy_values()
        self.assertEqual('user1', ctx_dict['user'])
        self.assertEqual('user1', ctx_dict['user_id'])
        self.assertEqual('tenant1', ctx_dict['tenant'])
        self.assertEqual('tenant1', ctx_dict['project_id'])
        self.assertEqual('somename', ctx_dict['project_name'])
        self.assertTrue(ctx_dict['is_public_api'])
        self.assertTrue(ctx_dict['is_admin_project'])
        self.assertEqual('domain_id3', ctx_dict['domain_id'])
        self.assertEqual('TreeDomain', ctx_dict['domain_name'])
        self.assertEqual('domain_id3', ctx_dict['user_domain_id'])
        self.assertEqual('domain_id4', ctx_dict['project_domain_id'])
        self.assertEqual([], ctx_dict['roles'])

    def test_get_admin_context(self):
        admin_context = context.get_admin_context()
        self.assertTrue(admin_context.is_admin)

    @mock.patch.object(oslo_context, 'get_current')
    def test_thread_without_context(self, context_get_mock):
        self.context.update_store = mock.Mock()
        context_get_mock.return_value = None
        self.context.ensure_thread_contain_context()
        self.context.update_store.assert_called_once_with()

    @mock.patch.object(oslo_context, 'get_current')
    def test_thread_with_context(self, context_get_mock):
        self.context.update_store = mock.Mock()
        context_get_mock.return_value = self.context
        self.context.ensure_thread_contain_context()
        self.assertFalse(self.context.update_store.called)
