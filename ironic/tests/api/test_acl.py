# vim: tabstop=4 shiftwidth=4 softtabstop=4
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

from oslo.config import cfg

from ironic.api import acl
from ironic.db import api as db_api
from ironic.tests.api import base
from ironic.tests.api import utils
from ironic.tests.db import utils as db_utils


class TestACL(base.FunctionalTest):

    def setUp(self):
        super(TestACL, self).setUp()

        self.environ = {'fake.cache': utils.FakeMemcache()}
        self.fake_node = db_utils.get_test_node()
        self.dbapi = db_api.get_instance()
        self.node_path = '/nodes/%s' % self.fake_node['uuid']

    def get_json(self, path, expect_errors=False, headers=None, q=[], **param):
        return super(TestACL, self).get_json(path,
                                                expect_errors=expect_errors,
                                                headers=headers,
                                                q=q,
                                                extra_environ=self.environ,
                                                **param)

    def _make_app(self):
        cfg.CONF.set_override('cache', 'fake.cache', group=acl.OPT_GROUP_NAME)
        return super(TestACL, self)._make_app(enable_acl=True)

    def test_non_authenticated(self):
        response = self.get_json(self.node_path, expect_errors=True)
        self.assertEqual(response.status_int, 401)

    def test_authenticated(self):
        self.mox.StubOutWithMock(self.dbapi, 'get_node')
        self.dbapi.get_node(self.fake_node['uuid']).AndReturn(self.fake_node)
        self.mox.ReplayAll()

        response = self.get_json(self.node_path,
                                 headers={'X-Auth-Token': utils.ADMIN_TOKEN})

        self.assertEquals(response['uuid'], self.fake_node['uuid'])

    def test_non_admin(self):
        response = self.get_json(self.node_path,
                                 headers={'X-Auth-Token': utils.MEMBER_TOKEN},
                                 expect_errors=True)

        self.assertEqual(response.status_int, 403)

    def test_non_admin_with_admin_header(self):
        response = self.get_json(self.node_path,
                                 headers={'X-Auth-Token': utils.MEMBER_TOKEN,
                                          'X-Roles': 'admin'},
                                 expect_errors=True)

        self.assertEqual(response.status_int, 403)
