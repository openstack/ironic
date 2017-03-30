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

from keystonemiddleware import audit
import mock
from oslo_config import cfg

from ironic.common import exception
from ironic.tests.unit.api import base


CONF = cfg.CONF


class TestAuditMiddleware(base.BaseApiTest):
    """Provide a basic smoke test to ensure audit middleware is active.

    The tests below provide minimal confirmation that the audit middleware
    is called, and may be configured. For comprehensive tests, please consult
    the test suite in keystone audit_middleware.
    """

    @mock.patch.object(audit, 'AuditMiddleware')
    def test_enable_audit_request(self, mock_audit):
        CONF.audit.enabled = True
        self._make_app()
        mock_audit.assert_called_once_with(
            mock.ANY,
            audit_map_file=CONF.audit.audit_map_file,
            ignore_req_list=CONF.audit.ignore_req_list)

    @mock.patch.object(audit, 'AuditMiddleware')
    def test_enable_audit_request_error(self, mock_audit):
        CONF.audit.enabled = True
        mock_audit.side_effect = IOError("file access error")

        self.assertRaises(exception.InputFileError,
                          self._make_app)

    @mock.patch.object(audit, 'AuditMiddleware')
    def test_disable_audit_request(self, mock_audit):
        CONF.audit.enabled = False
        self._make_app()
        self.assertFalse(mock_audit.called)
