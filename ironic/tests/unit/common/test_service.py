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

from ironic.common import exception
from ironic.common import service
from ironic.tests import base


class TestWSGIService(base.TestCase):

    @mock.patch.object(service.app, 'VersionSelectorApplication')
    def test_reset_pool_size_to_default(self, mock_app):
        test_service = service.WSGIService("test_service")
        test_service.start()

        # Stopping the service, which in turn sets pool size to 0
        test_service.stop()
        self.assertEqual(0, test_service.server._pool.size)

        # Resetting pool size to default
        test_service.reset()
        test_service.start()
        self.assertTrue(test_service.server._pool.size > 0)
        self.assertTrue(mock_app.called)

    @mock.patch.object(service.wsgi, 'Server')
    def test_workers_set_default(self, wsgi_server):
        test_service = service.WSGIService("ironic_api")
        self.assertEqual(processutils.get_worker_count(),
                         test_service.workers)

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
