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
import ironic_inspector_client as client
import mock

from ironic.common import driver_factory
from ironic.common import exception
from ironic.common import states
from ironic.conductor import task_manager
from ironic.drivers.modules import inspector
from ironic.tests.unit.conductor import mgr_utils
from ironic.tests.unit.db import base as db_base
from ironic.tests.unit.objects import utils as obj_utils


class DisabledTestCase(db_base.DbTestCase):
    def _do_mock(self):
        # NOTE(dtantsur): fake driver always has inspection, using another one
        mgr_utils.mock_the_extension_manager("pxe_ipmitool")
        self.driver = driver_factory.get_driver("pxe_ipmitool")

    def test_disabled(self):
        self.config(enabled=False, group='inspector')
        self._do_mock()
        self.assertIsNone(self.driver.inspect)
        # Direct loading of the class is still possible
        inspector.Inspector()

    def test_enabled(self):
        self.config(enabled=True, group='inspector')
        self._do_mock()
        self.assertIsNotNone(self.driver.inspect)

    @mock.patch.object(inspector, 'client', None)
    def test_init_inspector_not_imported(self):
        self.assertRaises(exception.DriverLoadError,
                          inspector.Inspector)

    def test_init_ok(self):
        self.config(enabled=True, group='inspector')
        inspector.Inspector()


class BaseTestCase(db_base.DbTestCase):
    def setUp(self):
        super(BaseTestCase, self).setUp()
        self.config(enabled=True, group='inspector')
        mgr_utils.mock_the_extension_manager("fake_inspector")
        self.driver = driver_factory.get_driver("fake_inspector")
        self.node = obj_utils.get_test_node(self.context)
        self.task = mock.MagicMock(spec=task_manager.TaskManager)
        self.task.context = self.context
        self.task.shared = False
        self.task.node = self.node
        self.task.driver = self.driver
        self.api_version = (1, 0)
        # NOTE(pas-ha) force-reset  global inspector session object
        inspector._INSPECTOR_SESSION = None


class CommonFunctionsTestCase(BaseTestCase):
    def test_validate_ok(self):
        self.driver.inspect.validate(self.task)

    def test_get_properties(self):
        res = self.driver.inspect.get_properties()
        self.assertEqual({}, res)

    def test_create_if_enabled(self):
        res = inspector.Inspector.create_if_enabled('driver')
        self.assertIsInstance(res, inspector.Inspector)

    @mock.patch.object(inspector.LOG, 'info', autospec=True)
    def test_create_if_enabled_disabled(self, warn_mock):
        self.config(enabled=False, group='inspector')
        res = inspector.Inspector.create_if_enabled('driver')
        self.assertIsNone(res)
        self.assertTrue(warn_mock.called)


@mock.patch('ironic.common.keystone.get_auth',
            lambda _section, **kwargs: mock.sentinel.auth)
@mock.patch('ironic.common.keystone.get_session',
            lambda _section, **kwargs: mock.sentinel.session)
@mock.patch.object(eventlet, 'spawn_n', lambda f, *a, **kw: f(*a, **kw))
@mock.patch.object(client.ClientV1, 'introspect')
@mock.patch.object(client.ClientV1, '__init__', return_value=None)
class InspectHardwareTestCase(BaseTestCase):
    def test_ok(self, mock_init, mock_introspect):
        self.assertEqual(states.INSPECTING,
                         self.driver.inspect.inspect_hardware(self.task))
        mock_init.assert_called_once_with(
            session=mock.sentinel.session,
            api_version=self.api_version,
            inspector_url=None)
        mock_introspect.assert_called_once_with(self.node.uuid)

    def test_url(self, mock_init, mock_introspect):
        self.config(service_url='meow', group='inspector')
        self.assertEqual(states.INSPECTING,
                         self.driver.inspect.inspect_hardware(self.task))
        mock_init.assert_called_once_with(
            session=mock.sentinel.session,
            api_version=self.api_version,
            inspector_url='meow')
        mock_introspect.assert_called_once_with(self.node.uuid)

    @mock.patch.object(task_manager, 'acquire', autospec=True)
    def test_error(self, mock_acquire, mock_init, mock_introspect):
        mock_introspect.side_effect = RuntimeError('boom')
        self.driver.inspect.inspect_hardware(self.task)
        mock_introspect.assert_called_once_with(self.node.uuid)
        task = mock_acquire.return_value.__enter__.return_value
        self.assertIn('boom', task.node.last_error)
        task.process_event.assert_called_once_with('fail')

    def test_is_standalone(self, mock_init, mock_introspect):
        self.config(auth_strategy='noauth')
        self.assertEqual(states.INSPECTING,
                         self.driver.inspect.inspect_hardware(self.task))
        mock_init.assert_called_once_with(
            session=None,
            api_version=self.api_version,
            inspector_url=None)
        mock_introspect.assert_called_once_with(self.node.uuid)


@mock.patch('ironic.common.keystone.get_auth',
            lambda _section, **kwargs: mock.sentinel.auth)
@mock.patch('ironic.common.keystone.get_session',
            lambda _section, **kwargs: mock.sentinel.session)
@mock.patch.object(client.ClientV1, 'get_status')
@mock.patch.object(client.ClientV1, '__init__', return_value=None)
class CheckStatusTestCase(BaseTestCase):
    def setUp(self):
        super(CheckStatusTestCase, self).setUp()
        self.node.provision_state = states.INSPECTING

    def test_not_inspecting(self, mock_init, mock_get):
        self.node.provision_state = states.MANAGEABLE
        inspector._check_status(self.task)
        self.assertFalse(mock_get.called)

    def test_not_inspector(self, mock_init, mock_get):
        self.task.driver.inspect = object()
        inspector._check_status(self.task)
        self.assertFalse(mock_get.called)

    def test_not_finished(self, mock_init, mock_get):
        mock_get.return_value = {}
        inspector._check_status(self.task)
        mock_init.assert_called_once_with(
            session=mock.sentinel.session,
            api_version=self.api_version,
            inspector_url=None)
        mock_get.assert_called_once_with(self.node.uuid)
        self.assertFalse(self.task.process_event.called)

    def test_exception_ignored(self, mock_init, mock_get):
        mock_get.side_effect = RuntimeError('boom')
        inspector._check_status(self.task)
        mock_init.assert_called_once_with(
            session=mock.sentinel.session,
            api_version=self.api_version,
            inspector_url=None)
        mock_get.assert_called_once_with(self.node.uuid)
        self.assertFalse(self.task.process_event.called)

    def test_status_ok(self, mock_init, mock_get):
        mock_get.return_value = {'finished': True}
        inspector._check_status(self.task)
        mock_init.assert_called_once_with(
            session=mock.sentinel.session,
            api_version=self.api_version,
            inspector_url=None)
        mock_get.assert_called_once_with(self.node.uuid)
        self.task.process_event.assert_called_once_with('done')

    def test_status_error(self, mock_init, mock_get):
        mock_get.return_value = {'error': 'boom'}
        inspector._check_status(self.task)
        mock_init.assert_called_once_with(
            session=mock.sentinel.session,
            api_version=self.api_version,
            inspector_url=None)
        mock_get.assert_called_once_with(self.node.uuid)
        self.task.process_event.assert_called_once_with('fail')
        self.assertIn('boom', self.node.last_error)

    def test_service_url(self, mock_init, mock_get):
        self.config(service_url='meow', group='inspector')
        mock_get.return_value = {'finished': True}
        inspector._check_status(self.task)
        mock_init.assert_called_once_with(
            session=mock.sentinel.session,
            api_version=self.api_version,
            inspector_url='meow')
        mock_get.assert_called_once_with(self.node.uuid)
        self.task.process_event.assert_called_once_with('done')

    def test_is_standalone(self, mock_init, mock_get):
        self.config(auth_strategy='noauth')
        mock_get.return_value = {'finished': True}
        inspector._check_status(self.task)
        mock_init.assert_called_once_with(
            session=None,
            api_version=self.api_version,
            inspector_url=None)
        mock_get.assert_called_once_with(self.node.uuid)
        self.task.process_event.assert_called_once_with('done')
