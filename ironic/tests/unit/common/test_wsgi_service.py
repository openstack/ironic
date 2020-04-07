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

from oslo_concurrency import processutils
from oslo_config import cfg

from ironic.common import exception
from ironic.common import wsgi_service
from ironic.tests import base

CONF = cfg.CONF


class TestWSGIService(base.TestCase):
    @mock.patch.object(wsgi_service.wsgi, 'Server', autospec=True)
    def test_workers_set_default(self, mock_server):
        service_name = "ironic_api"
        test_service = wsgi_service.WSGIService(service_name)
        self.assertEqual(processutils.get_worker_count(),
                         test_service.workers)
        mock_server.assert_called_once_with(CONF, service_name,
                                            test_service.app,
                                            host='0.0.0.0',
                                            port=6385,
                                            use_ssl=False)

    @mock.patch.object(wsgi_service.wsgi, 'Server', autospec=True)
    def test_workers_set_correct_setting(self, mock_server):
        self.config(api_workers=8, group='api')
        test_service = wsgi_service.WSGIService("ironic_api")
        self.assertEqual(8, test_service.workers)

    @mock.patch.object(wsgi_service.wsgi, 'Server', autospec=True)
    def test_workers_set_zero_setting(self, mock_server):
        self.config(api_workers=0, group='api')
        test_service = wsgi_service.WSGIService("ironic_api")
        self.assertEqual(processutils.get_worker_count(), test_service.workers)

    @mock.patch.object(wsgi_service.wsgi, 'Server', autospec=True)
    def test_workers_set_negative_setting(self, mock_server):
        self.config(api_workers=-2, group='api')
        self.assertRaises(exception.ConfigInvalid,
                          wsgi_service.WSGIService,
                          'ironic_api')
        self.assertFalse(mock_server.called)

    @mock.patch.object(wsgi_service.wsgi, 'Server', autospec=True)
    def test_wsgi_service_with_ssl_enabled(self, mock_server):
        self.config(enable_ssl_api=True, group='api')
        service_name = 'ironic_api'
        srv = wsgi_service.WSGIService('ironic_api', CONF.api.enable_ssl_api)
        mock_server.assert_called_once_with(CONF, service_name,
                                            srv.app,
                                            host='0.0.0.0',
                                            port=6385,
                                            use_ssl=True)
