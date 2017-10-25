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
from oslo_config import cfg
from osprofiler import web

from ironic.tests.unit.api import base

CONF = cfg.CONF


class TestOsprofilerWsgiMiddleware(base.BaseApiTest):
    """Provide a basic test for OSProfiler wsgi middleware.

    The tests below provide minimal confirmation that the OSProfiler wsgi
    middleware is called.
    """

    def setUp(self):
        super(TestOsprofilerWsgiMiddleware, self).setUp()

    @mock.patch.object(web, 'WsgiMiddleware')
    def test_enable_osp_wsgi_request(self, mock_ospmiddleware):
        CONF.profiler.enabled = True
        self._make_app()
        mock_ospmiddleware.assert_called_once_with(mock.ANY)

    @mock.patch.object(web, 'WsgiMiddleware')
    def test_disable_osp_wsgi_request(self, mock_ospmiddleware):
        CONF.profiler.enabled = False
        self._make_app()
        self.assertFalse(mock_ospmiddleware.called)
