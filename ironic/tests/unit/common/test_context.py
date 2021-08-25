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

from unittest import mock

from oslo_context import context as oslo_context

from ironic.common import context
from ironic.tests import base as tests_base


class RequestContextTestCase(tests_base.TestCase):
    def setUp(self):
        super(RequestContextTestCase, self).setUp()
        self.context_dict = {
            'auth_token': 'auth_token1',
            "user_id": "user1",
            "project_id": "project1",
            "project_name": "somename",
            'read_only': True,
            'show_deleted': True,
            'request_id': 'id1',
            "is_public_api": True,
            "domain_id": "domain_id2",
            "user_domain_id": "domain_id3",
            "user_domain_name": "TreeDomain",
            "project_domain_id": "domain_id4",
            "roles": None,
            "overwrite": True
        }

    @mock.patch.object(oslo_context.RequestContext, "__init__", autospec=True)
    def test_create_context(self, context_mock):
        test_context = context.RequestContext()
        context_mock.assert_called_once_with(mock.ANY)
        self.assertFalse(test_context.is_public_api)

    def test_to_policy_values(self):
        ctx = context.RequestContext(**self.context_dict)
        ctx_dict = ctx.to_policy_values()
        self.assertEqual('somename', ctx_dict['project_name'])
        self.assertTrue(ctx_dict['is_public_api'])

    @mock.patch.object(oslo_context, 'get_current', autospec=True)
    def test_thread_without_context(self, context_get_mock):
        self.context.update_store = mock.Mock()
        context_get_mock.return_value = None
        self.context.ensure_thread_contain_context()
        self.context.update_store.assert_called_once_with()

    @mock.patch.object(oslo_context, 'get_current', autospec=True)
    def test_thread_with_context(self, context_get_mock):
        self.context.update_store = mock.Mock()
        context_get_mock.return_value = self.context
        self.context.ensure_thread_contain_context()
        self.assertFalse(self.context.update_store.called)
