
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
Tests to assert that proxy headers middleware works as expected.
"""
from oslo_config import cfg

from ironic.tests.unit.api import base


CONF = cfg.CONF


class TestProxyHeadersMiddleware(base.BaseApiTest):
    """Provide a basic smoke test to ensure proxy headers middleware works."""

    def setUp(self):
        CONF.set_override('public_endpoint', 'http://spam.ham/eggs',
                          group='api')
        self.proxy_headers = {"X-Forwarded-Proto": "https",
                              "X-Forwarded-Host": "mycloud.com",
                              "X-Forwarded-Prefix": "/ironic"}
        super(TestProxyHeadersMiddleware, self).setUp()

    def test_proxy_headers_enabled(self):
        """Test enabled proxy headers middleware overriding public_endpoint"""
        # NOTE(pas-ha) setting config option and re-creating app
        # as the middleware registers its config option on instantiation
        CONF.set_override('enable_proxy_headers_parsing', True,
                          group='oslo_middleware')
        self.app = self._make_app()
        response = self.get_json('/', path_prefix="",
                                 headers=self.proxy_headers)
        href = response["default_version"]["links"][0]["href"]
        self.assertTrue(href.startswith("https://mycloud.com/ironic"))

    def test_proxy_headers_disabled(self):
        """Test proxy headers middleware disabled by default"""
        response = self.get_json('/', path_prefix="",
                                 headers=self.proxy_headers)
        href = response["default_version"]["links"][0]["href"]
        # check that [api]public_endpoint is used when proxy headers parsing
        # is disabled
        self.assertTrue(href.startswith("http://spam.ham/eggs"))
