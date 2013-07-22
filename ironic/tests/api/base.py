# vim: tabstop=4 shiftwidth=4 softtabstop=4
# -*- encoding: utf-8 -*-
#
# Copyright 2013 Hewlett-Packard Development Company, L.P.
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
"""Base classes for API tests."""

# NOTE: Ported from ceilometer/tests/api.py
#       https://bugs.launchpad.net/ceilometer/+bug/1193666

from oslo.config import cfg
import pecan
import pecan.testing

from ironic.api import acl
from ironic.db import api as dbapi
from ironic.tests.db import base


class FunctionalTest(base.DbTestCase):
    """Used for functional tests of Pecan controllers where you need to
    test your literal application and its integration with the
    framework.
    """

    PATH_PREFIX = '/v1'

    SOURCE_DATA = {'test_source': {'somekey': '666'}}

    def setUp(self):
        super(FunctionalTest, self).setUp()
        cfg.CONF.set_override("auth_version", "v2.0", group=acl.OPT_GROUP_NAME)
        cfg.CONF.set_override("policy_file",
                              self.path_get('tests/policy.json'))
        self.app = self._make_app()
        self.dbapi = dbapi.get_instance()

    def _make_app(self, enable_acl=False):
        # Determine where we are so we can set up paths in the config
        root_dir = self.path_get()

        self.config = {
            'app': {
                'root': 'ironic.api.controllers.root.RootController',
                'modules': ['ironic.api'],
                'static_root': '%s/public' % root_dir,
                'template_path': '%s/api/templates' % root_dir,
                'enable_acl': enable_acl,
            },
        }

        return pecan.testing.load_test_app(self.config)

    def tearDown(self):
        super(FunctionalTest, self).tearDown()
        pecan.set_config({}, overwrite=True)

    def patch_json(self, path, params, expect_errors=False, headers=None,
                 extra_environ=None, status=None):
        return self.post_json(path=path, params=params,
                              expect_errors=expect_errors,
                              headers=headers, extra_environ=extra_environ,
                              status=status, method="patch")

    def put_json(self, path, params, expect_errors=False, headers=None,
                 extra_environ=None, status=None):
        return self.post_json(path=path, params=params,
                              expect_errors=expect_errors,
                              headers=headers, extra_environ=extra_environ,
                              status=status, method="put")

    def post_json(self, path, params, expect_errors=False, headers=None,
                  method="post", extra_environ=None, status=None):
        full_path = self.PATH_PREFIX + path
        print('%s: %s %s' % (method.upper(), full_path, params))
        response = getattr(self.app, "%s_json" % method)(
            str(full_path),
            params=params,
            headers=headers,
            status=status,
            extra_environ=extra_environ,
            expect_errors=expect_errors
        )
        print('GOT:%s' % response)
        return response

    def delete(self, path, expect_errors=False, headers=None,
               extra_environ=None, status=None):
        full_path = self.PATH_PREFIX + path
        print('DELETE: %s' % (full_path))
        response = self.app.delete(str(full_path),
                                   headers=headers,
                                   status=status,
                                   extra_environ=extra_environ,
                                   expect_errors=expect_errors)
        print('GOT:%s' % response)
        return response

    def get_json(self, path, expect_errors=False, headers=None,
                 extra_environ=None, q=[], **params):
        full_path = self.PATH_PREFIX + path
        query_params = {'q.field': [],
                        'q.value': [],
                        'q.op': [],
                        }
        for query in q:
            for name in ['field', 'op', 'value']:
                query_params['q.%s' % name].append(query.get(name, ''))
        all_params = {}
        all_params.update(params)
        if q:
            all_params.update(query_params)
        print('GET: %s %r' % (full_path, all_params))
        response = self.app.get(full_path,
                                params=all_params,
                                headers=headers,
                                extra_environ=extra_environ,
                                expect_errors=expect_errors)
        if not expect_errors:
            response = response.json
        print('GOT:%s' % response)
        return response
