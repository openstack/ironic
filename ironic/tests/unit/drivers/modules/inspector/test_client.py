# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

from unittest import mock

from keystoneauth1 import exceptions as ks_exception
import openstack

from ironic.common import context
from ironic.common import exception
from ironic.conf import CONF
from ironic.drivers.modules.inspector import client
from ironic.tests.unit.db import base as db_base


@mock.patch('ironic.common.keystone.get_auth', autospec=True,
            return_value=mock.sentinel.auth)
@mock.patch('ironic.common.keystone.get_session', autospec=True,
            return_value=mock.sentinel.session)
@mock.patch.object(openstack.connection, 'Connection', autospec=True)
class GetClientTestCase(db_base.DbTestCase):

    def setUp(self):
        super(GetClientTestCase, self).setUp()
        # NOTE(pas-ha) force-reset  global inspector session object
        client._INSPECTOR_SESSION = None
        self.context = context.RequestContext(global_request_id='global')

    def test_get_client(self, mock_conn, mock_session, mock_auth):
        client.get_client(self.context)
        mock_conn.assert_called_once_with(
            session=mock.sentinel.session,
            oslo_conf=mock.ANY)
        self.assertEqual(1, mock_auth.call_count)
        self.assertEqual(1, mock_session.call_count)

    def test_get_client_standalone(self, mock_conn, mock_session, mock_auth):
        self.config(auth_strategy='noauth')
        client.get_client(self.context)
        self.assertEqual('none', CONF.inspector.auth_type)
        mock_conn.assert_called_once_with(
            session=mock.sentinel.session,
            oslo_conf=mock.ANY)
        self.assertEqual(1, mock_auth.call_count)
        self.assertEqual(1, mock_session.call_count)

    def test_get_client_connection_problem(
            self, mock_conn, mock_session, mock_auth):
        mock_conn.side_effect = ks_exception.DiscoveryFailure("")
        self.assertRaises(exception.ConfigInvalid,
                          client.get_client, self.context)
        mock_conn.assert_called_once_with(
            session=mock.sentinel.session,
            oslo_conf=mock.ANY)
        self.assertEqual(1, mock_auth.call_count)
        self.assertEqual(1, mock_session.call_count)
