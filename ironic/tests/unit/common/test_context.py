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

    @mock.patch.object(oslo_context.RequestContext, "__init__")
    def test_create_context(self, context_mock):
        test_context = context.RequestContext()
        context_mock.assert_called_once_with(
            auth_token=None, user=None, tenant=None, is_admin=False,
            read_only=False, show_deleted=False, request_id=None,
            overwrite=True)
        self.assertFalse(test_context.is_public_api)
        self.assertIsNone(test_context.domain_id)
        self.assertIsNone(test_context.domain_name)
        self.assertEqual([], test_context.roles)

    def test_from_dict(self):
        dict = {
            "user": "user1",
            "tenant": "tenant1",
            "is_public_api": True,
            "domain_id": "domain_id1",
            "domain_name": "domain_name1",
            "roles": None
        }
        ctx = context.RequestContext.from_dict(dict)
        self.assertIsNone(ctx.user)
        self.assertIsNone(ctx.tenant)
        self.assertTrue(ctx.is_public_api)
        self.assertEqual("domain_id1", ctx.domain_id)
        self.assertEqual("domain_name1", ctx.domain_name)
        self.assertEqual([], ctx.roles)

    def test_to_dict(self):
        values = {
            'auth_token': 'auth_token1',
            "user": "user1",
            "tenant": "tenant1",
            'is_admin': True,
            'read_only': True,
            'show_deleted': True,
            'request_id': 'id1',
            "is_public_api": True,
            "domain_id": "domain_id1",
            "domain_name": "domain_name1",
            "roles": None,
            "overwrite": True
        }
        ctx = context.RequestContext(**values)
        ctx_dict = ctx.to_dict()
        self.assertIn('auth_token', ctx_dict)
        self.assertIn('user', ctx_dict)
        self.assertIn('tenant', ctx_dict)
        self.assertIn('is_admin', ctx_dict)
        self.assertIn('read_only', ctx_dict)
        self.assertIn('show_deleted', ctx_dict)
        self.assertIn('request_id', ctx_dict)
        self.assertIn('domain_id', ctx_dict)
        self.assertIn('roles', ctx_dict)
        self.assertIn('domain_name', ctx_dict)
        self.assertIn('is_public_api', ctx_dict)
        self.assertNotIn('overwrite', ctx_dict)

        self.assertEqual('auth_token1', ctx_dict['auth_token'])
        self.assertEqual('user1', ctx_dict['user'])
        self.assertEqual('tenant1', ctx_dict['tenant'])
        self.assertTrue(ctx_dict['is_admin'])
        self.assertTrue(ctx_dict['read_only'])
        self.assertTrue(ctx_dict['show_deleted'])
        self.assertEqual('id1', ctx_dict['request_id'])
        self.assertTrue(ctx_dict['is_public_api'])
        self.assertEqual('domain_id1', ctx_dict['domain_id'])
        self.assertEqual('domain_name1', ctx_dict['domain_name'])
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
