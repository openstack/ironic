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

import ddt
from oslo_config import cfg

from ironic.tests.unit.api import base
from ironic.tests.unit.api import utils
from ironic.tests.unit.db import utils as db_utils

cfg.CONF.import_opt('cache', 'keystonemiddleware.auth_token',
                    group='keystone_authtoken')


class TestACLBase(base.BaseApiTest):

    def setUp(self):
        super(TestACLBase, self).setUp()

        self.environ = {'fake.cache': utils.FakeMemcache()}
        self.format_data = {}
        self._create_test_data()

    def _make_app(self):
        cfg.CONF.set_override('cache', 'fake.cache',
                              group='keystone_authtoken')
        cfg.CONF.set_override('auth_strategy', 'keystone')
        return super(TestACLBase, self)._make_app()

    @abc.abstractmethod
    def _create_test_data(self):
        pass

    def _test_request(self, path, params=None, headers=None, method='get',
                      assert_status=None, assert_dict_contains=None):
        path = path.format(**self.format_data)
        expect_errors = bool(assert_status)
        if method == 'get':
            response = self.get_json(
                path,
                headers=headers,
                expect_errors=expect_errors,
                extra_environ=self.environ,
                path_prefix=''
            )
        else:
            assert False, 'Unimplemented test method: %s' % method

        if assert_status:
            self.assertEqual(assert_status, response.status_int)

        if assert_dict_contains:
            for k, v in assert_dict_contains.items():
                self.assertIn(k, response)
                self.assertEqual(v.format(**self.format_data), response[k])


@ddt.ddt
class TestACLBasic(TestACLBase):

    def _create_test_data(self):
        fake_db_node = db_utils.create_test_node(chassis_id=None)
        self.format_data['node_uuid'] = fake_db_node['uuid']

    @ddt.file_data('test_acl_basic.yaml')
    @ddt.unpack
    def test_basic(self, **kwargs):
        self._test_request(**kwargs)
