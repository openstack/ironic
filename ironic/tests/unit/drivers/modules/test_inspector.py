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

import eventlet
import mock
import openstack

from ironic.common import context
from ironic.common import states
from ironic.conductor import task_manager
from ironic.drivers.modules import inspector
from ironic.tests.unit.db import base as db_base
from ironic.tests.unit.objects import utils as obj_utils


@mock.patch('ironic.common.keystone.get_auth', autospec=True,
            return_value=mock.sentinel.auth)
@mock.patch('ironic.common.keystone.get_session', autospec=True,
            return_value=mock.sentinel.session)
@mock.patch.object(openstack.connection, 'Connection', autospec=True)
class GetClientTestCase(db_base.DbTestCase):

    def setUp(self):
        super(GetClientTestCase, self).setUp()
        # NOTE(pas-ha) force-reset  global inspector session object
        inspector._INSPECTOR_SESSION = None
        self.context = context.RequestContext(global_request_id='global')

    def test__get_client(self, mock_conn, mock_session, mock_auth):
        inspector._get_client(self.context)
        mock_conn.assert_called_once_with(
            session=mock.sentinel.session,
            oslo_conf=mock.ANY)
        self.assertEqual(1, mock_auth.call_count)
        self.assertEqual(1, mock_session.call_count)

    def test__get_client_standalone(self, mock_conn, mock_session, mock_auth):
        self.config(auth_strategy='noauth')
        inspector._get_client(self.context)
        self.assertEqual('none', inspector.CONF.inspector.auth_type)
        mock_conn.assert_called_once_with(
            session=mock.sentinel.session,
            oslo_conf=mock.ANY)
        self.assertEqual(1, mock_auth.call_count)
        self.assertEqual(1, mock_session.call_count)


class BaseTestCase(db_base.DbTestCase):
    def setUp(self):
        super(BaseTestCase, self).setUp()
        self.node = obj_utils.get_test_node(self.context,
                                            inspect_interface='inspector')
        self.iface = inspector.Inspector()
        self.task = mock.MagicMock(spec=task_manager.TaskManager)
        self.task.context = self.context
        self.task.shared = False
        self.task.node = self.node
        self.task.driver = mock.Mock(spec=['inspect'], inspect=self.iface)


class CommonFunctionsTestCase(BaseTestCase):
    def test_validate_ok(self):
        self.iface.validate(self.task)

    def test_get_properties(self):
        res = self.iface.get_properties()
        self.assertEqual({}, res)


@mock.patch.object(eventlet, 'spawn_n', lambda f, *a, **kw: f(*a, **kw))
@mock.patch('ironic.drivers.modules.inspector._get_client', autospec=True)
class InspectHardwareTestCase(BaseTestCase):
    def test_ok(self, mock_client):
        mock_introspect = mock_client.return_value.start_introspection
        self.assertEqual(states.INSPECTWAIT,
                         self.iface.inspect_hardware(self.task))
        mock_introspect.assert_called_once_with(self.node.uuid)

    @mock.patch.object(task_manager, 'acquire', autospec=True)
    def test_error(self, mock_acquire, mock_client):
        mock_introspect = mock_client.return_value.start_introspection
        mock_introspect.side_effect = RuntimeError('boom')
        self.iface.inspect_hardware(self.task)
        mock_introspect.assert_called_once_with(self.node.uuid)
        task = mock_acquire.return_value.__enter__.return_value
        self.assertIn('boom', task.node.last_error)
        task.process_event.assert_called_once_with('fail')


@mock.patch('ironic.drivers.modules.inspector._get_client', autospec=True)
class CheckStatusTestCase(BaseTestCase):
    def setUp(self):
        super(CheckStatusTestCase, self).setUp()
        self.node.provision_state = states.INSPECTWAIT

    def test_not_inspecting(self, mock_client):
        mock_get = mock_client.return_value.get_introspection
        self.node.provision_state = states.MANAGEABLE
        inspector._check_status(self.task)
        self.assertFalse(mock_get.called)

    def test_not_check_inspecting(self, mock_client):
        mock_get = mock_client.return_value.get_introspection
        self.node.provision_state = states.INSPECTING
        inspector._check_status(self.task)
        self.assertFalse(mock_get.called)

    def test_not_inspector(self, mock_client):
        mock_get = mock_client.return_value.get_introspection
        self.task.driver.inspect = object()
        inspector._check_status(self.task)
        self.assertFalse(mock_get.called)

    def test_not_finished(self, mock_client):
        mock_get = mock_client.return_value.get_introspection
        mock_get.return_value = mock.Mock(is_finished=False,
                                          error=None,
                                          spec=['is_finished', 'error'])
        inspector._check_status(self.task)
        mock_get.assert_called_once_with(self.node.uuid)
        self.assertFalse(self.task.process_event.called)

    def test_exception_ignored(self, mock_client):
        mock_get = mock_client.return_value.get_introspection
        mock_get.side_effect = RuntimeError('boom')
        inspector._check_status(self.task)
        mock_get.assert_called_once_with(self.node.uuid)
        self.assertFalse(self.task.process_event.called)

    def test_status_ok(self, mock_client):
        mock_get = mock_client.return_value.get_introspection
        mock_get.return_value = mock.Mock(is_finished=True,
                                          error=None,
                                          spec=['is_finished', 'error'])
        inspector._check_status(self.task)
        mock_get.assert_called_once_with(self.node.uuid)
        self.task.process_event.assert_called_once_with('done')

    def test_status_error(self, mock_client):
        mock_get = mock_client.return_value.get_introspection
        mock_get.return_value = mock.Mock(is_finished=True,
                                          error='boom',
                                          spec=['is_finished', 'error'])
        inspector._check_status(self.task)
        mock_get.assert_called_once_with(self.node.uuid)
        self.task.process_event.assert_called_once_with('fail')
        self.assertIn('boom', self.node.last_error)


@mock.patch('ironic.drivers.modules.inspector._get_client', autospec=True)
class InspectHardwareAbortTestCase(BaseTestCase):
    def test_abort_ok(self, mock_client):
        mock_abort = mock_client.return_value.abort_introspection
        self.iface.abort(self.task)
        mock_abort.assert_called_once_with(self.node.uuid)

    def test_abort_error(self, mock_client):
        mock_abort = mock_client.return_value.abort_introspection
        mock_abort.side_effect = RuntimeError('boom')
        self.assertRaises(RuntimeError, self.iface.abort, self.task)
        mock_abort.assert_called_once_with(self.node.uuid)
