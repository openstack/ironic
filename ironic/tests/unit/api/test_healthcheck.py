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
Tests to assert that audit middleware works as expected.
"""

from unittest import mock

from oslo_config import cfg
from oslo_middleware import healthcheck

from ironic.tests.unit.api import base


CONF = cfg.CONF


class TestHealthcheckMiddleware(base.BaseApiTest):
    """Provide a basic smoke test to ensure healthcheck middleware works."""

    @mock.patch.object(healthcheck, 'Healthcheck')
    def test_enable(self, mock_healthcheck):
        CONF.set_override('enabled', True, group='healthcheck')
        self._make_app()
        mock_healthcheck.assert_called_once_with(mock.ANY, CONF)

    @mock.patch.object(healthcheck, 'Healthcheck')
    def test_disable(self, mock_healthcheck):
        CONF.set_override('enabled', False, group='healthcheck')
        self._make_app()
        self.assertFalse(mock_healthcheck.called)
