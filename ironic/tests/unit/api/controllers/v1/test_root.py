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

from unittest import mock

from webob import exc as webob_exc

from ironic.api.controllers import v1 as v1_api
from ironic.tests import base as test_base
from ironic.tests.unit.api import base as api_base


class TestV1Routing(api_base.BaseApiTest):
    def test_route_checks_version(self):
        self.get_json('/')
        self._check_version.assert_called_once_with(mock.ANY,
                                                    mock.ANY)


class TestCheckVersions(test_base.TestCase):

    def setUp(self):
        super(TestCheckVersions, self).setUp()

        class ver(object):
            major = None
            minor = None

        self.version = ver()

    def test_check_version_invalid_major_version(self):
        self.version.major = v1_api.BASE_VERSION + 1
        self.version.minor = v1_api.min_version().minor
        self.assertRaises(
            webob_exc.HTTPNotAcceptable,
            v1_api.Controller()._check_version,
            self.version)

    def test_check_version_too_low(self):
        self.version.major = v1_api.BASE_VERSION
        self.version.minor = v1_api.min_version().minor - 1
        self.assertRaises(
            webob_exc.HTTPNotAcceptable,
            v1_api.Controller()._check_version,
            self.version)

    def test_check_version_too_high(self):
        self.version.major = v1_api.BASE_VERSION
        self.version.minor = v1_api.max_version().minor + 1
        e = self.assertRaises(
            webob_exc.HTTPNotAcceptable,
            v1_api.Controller()._check_version,
            self.version, {'fake-headers': v1_api.max_version().minor})
        self.assertEqual(v1_api.max_version().minor, e.headers['fake-headers'])

    def test_check_version_ok(self):
        self.version.major = v1_api.BASE_VERSION
        self.version.minor = v1_api.min_version().minor
        v1_api.Controller()._check_version(self.version)
