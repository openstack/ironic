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
from oslo_concurrency import processutils
from oslo_config import cfg
import oslo_messaging
from oslo_service import service as base_service

from ironic.common import context
from ironic.common import exception
from ironic.common import rpc
from ironic.common import service
from ironic.conductor import manager
from ironic.objects import base as objects_base
from ironic.tests import base

CONF = cfg.CONF


@mock.patch.object(base_service.Service, '__init__', lambda *_, **__: None)
class TestRPCService(base.TestCase):

    def setUp(self):
        super(TestRPCService, self).setUp()
        host = "fake_host"
        mgr_module = "ironic.conductor.manager"
        mgr_class = "ConductorManager"
        self.rpc_svc = service.RPCService(host, mgr_module, mgr_class)

    @mock.patch.object(oslo_messaging, 'Target', autospec=True)
    @mock.patch.object(objects_base, 'IronicObjectSerializer', autospec=True)
    @mock.patch.object(rpc, 'get_server', autospec=True)
    @mock.patch.object(manager.ConductorManager, 'init_host', autospec=True)
    @mock.patch.object(context, 'get_admin_context', autospec=True)
    def test_start(self, mock_ctx, mock_init_method,
                   mock_rpc, mock_ios, mock_target):
        mock_rpc.return_value.start = mock.MagicMock()
        self.rpc_svc.handle_signal = mock.MagicMock()
        self.rpc_svc.start()
        mock_ctx.assert_called_once_with()
        mock_target.assert_called_once_with(topic=self.rpc_svc.topic,
                                            server="fake_host")
        mock_ios.assert_called_once_with()
        mock_init_method.assert_called_once_with(self.rpc_svc.manager,
                                                 mock_ctx.return_value)


class TestWSGIService(base.TestCase):
    @mock.patch.object(service.wsgi, 'Server')
    def test_workers_set_default(self, wsgi_server):
        service_name = "ironic_api"
        test_service = service.WSGIService(service_name)
        self.assertEqual(processutils.get_worker_count(),
                         test_service.workers)
        wsgi_server.assert_called_once_with(CONF, service_name,
                                            test_service.app,
                                            host='0.0.0.0',
                                            port=6385,
                                            use_ssl=False)

    @mock.patch.object(service.wsgi, 'Server')
    def test_workers_set_correct_setting(self, wsgi_server):
        self.config(api_workers=8, group='api')
        test_service = service.WSGIService("ironic_api")
        self.assertEqual(8, test_service.workers)

    @mock.patch.object(service.wsgi, 'Server')
    def test_workers_set_zero_setting(self, wsgi_server):
        self.config(api_workers=0, group='api')
        test_service = service.WSGIService("ironic_api")
        self.assertEqual(processutils.get_worker_count(), test_service.workers)

    @mock.patch.object(service.wsgi, 'Server')
    def test_workers_set_negative_setting(self, wsgi_server):
        self.config(api_workers=-2, group='api')
        self.assertRaises(exception.ConfigInvalid,
                          service.WSGIService,
                          'ironic_api')
        self.assertFalse(wsgi_server.called)

    @mock.patch.object(service.wsgi, 'Server')
    def test_wsgi_service_with_ssl_enabled(self, wsgi_server):
        self.config(enable_ssl_api=True, group='api')
        service_name = 'ironic_api'
        srv = service.WSGIService('ironic_api', CONF.api.enable_ssl_api)
        wsgi_server.assert_called_once_with(CONF, service_name,
                                            srv.app,
                                            host='0.0.0.0',
                                            port=6385,
                                            use_ssl=True)
