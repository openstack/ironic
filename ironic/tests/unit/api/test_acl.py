# -*- encoding: utf-8 -*-
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
Tests for ACL. Checks whether certain kinds of requests
are blocked or allowed to be processed.
"""

import abc
from unittest import mock

import ddt
from keystonemiddleware import auth_token
from oslo_config import cfg

from ironic.tests.unit.api import base
from ironic.tests.unit.db import utils as db_utils


class TestACLBase(base.BaseApiTest):

    def setUp(self):
        super(TestACLBase, self).setUp()

        self.environ = {}
        self.format_data = {}
        self._create_test_data()
        self.fake_token = None
        mock_auth = mock.patch.object(
            auth_token.AuthProtocol, 'process_request',
            autospec=True)
        self.mock_auth = mock_auth.start()
        self.addCleanup(mock_auth.stop)

    def _make_app(self):
        cfg.CONF.set_override('auth_strategy', 'keystone')
        return super(TestACLBase, self)._make_app()

    @abc.abstractmethod
    def _create_test_data(self):
        pass

    def _check_skip(self, **kwargs):
        if kwargs.get('skip_reason'):
            self.skipTest(kwargs.get('skip_reason'))
        # Remove ASAP, but as a few hundred tests use this, we can
        # rip it out later.
        if kwargs.get('skip'):
            self.skipTest(kwargs.get('skip_reason', 'Not implemented'))

    def _fake_process_request(self, request, auth_token_request):
        pass

    def _test_request(self, path, params=None, headers=None, method='get',
                      assert_status=None, assert_dict_contains=None):
        path = path.format(**self.format_data)
        self.mock_auth.side_effect = self._fake_process_request

        if method == 'get':
            response = self.get_json(
                path,
                headers=headers,
                expect_errors=True,
                extra_environ=self.environ,
                path_prefix=''
            )
        else:
            assert False, 'Unimplemented test method: %s' % method

        other_asserts = bool(assert_dict_contains)

        if assert_status:
            self.assertEqual(assert_status, response.status_int)
        else:
            self.assertIsNotNone(other_asserts,
                                 'Tests must include an assert_status')

        if assert_dict_contains:
            for k, v in assert_dict_contains.items():
                self.assertIn(k, response)
                self.assertEqual(v.format(**self.format_data),
                                 response.json[k])


@ddt.ddt
class TestRBACBasic(TestACLBase):

    def _create_test_data(self):
        fake_db_node = db_utils.create_test_node(chassis_id=None)
        self.format_data['node_uuid'] = fake_db_node['uuid']

    @ddt.file_data('test_acl_basic.yaml')
    @ddt.unpack
    def test_basic(self, **kwargs):
        self._check_skip(**kwargs)
        self._test_request(**kwargs)


@ddt.ddt
class TestRBACModelBeforeScopes(TestACLBase):

    def _create_test_data(self):
        fake_db_node = db_utils.create_test_node(chassis_id=None)
        self.format_data['node_ident'] = fake_db_node['uuid']

    @ddt.file_data('test_rbac_legacy.yaml')
    @ddt.unpack
    def test_rbac_legacy(self, **kwargs):
        self._check_skip(**kwargs)
        self._test_request(**kwargs)
