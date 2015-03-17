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
import ironic_discoverd
from ironic_discoverd import client
import mock

from ironic.common import driver_factory
from ironic.common import exception
from ironic.common import keystone
from ironic.common import states
from ironic.conductor import task_manager
from ironic.drivers.modules import discoverd
from ironic.tests.conductor import utils as mgr_utils
from ironic.tests.db import base as db_base
from ironic.tests.objects import utils as obj_utils


class DisabledTestCase(db_base.DbTestCase):
    def setUp(self):
        super(DisabledTestCase, self).setUp()

    def _do_mock(self):
        # NOTE(dtantsur): fake driver always has inspection, using another one
        mgr_utils.mock_the_extension_manager("pxe_ssh")
        self.driver = driver_factory.get_driver("pxe_ssh")

    def test_disabled(self):
        self.config(enabled=False, group='discoverd')
        self._do_mock()
        self.assertIsNone(self.driver.inspect)
        # NOTE(dtantsur): it's expected that fake_discoverd fails to load
        # in this case
        self.assertRaises(exception.DriverLoadError,
                          mgr_utils.mock_the_extension_manager,
                          "fake_discoverd")

    def test_enabled(self):
        self.config(enabled=True, group='discoverd')
        self._do_mock()
        self.assertIsNotNone(self.driver.inspect)

    @mock.patch.object(discoverd, 'ironic_discoverd', None)
    def test_init_discoverd_not_imported(self):
        self.assertRaises(exception.DriverLoadError,
                          discoverd.DiscoverdInspect)

    @mock.patch.object(ironic_discoverd, '__version_info__', (1, 0, 0))
    def test_init_ok(self):
        self.config(enabled=True, group='discoverd')
        discoverd.DiscoverdInspect()

    @mock.patch.object(ironic_discoverd, '__version_info__', (0, 2, 2))
    def test_init_old_version(self):
        self.config(enabled=True, group='discoverd')
        self.assertRaises(exception.DriverLoadError,
                          discoverd.DiscoverdInspect)


class BaseTestCase(db_base.DbTestCase):
    def setUp(self):
        super(BaseTestCase, self).setUp()
        self.config(enabled=True, group='discoverd')
        mgr_utils.mock_the_extension_manager("fake_discoverd")
        self.driver = driver_factory.get_driver("fake_discoverd")
        self.node = obj_utils.get_test_node(self.context)
        self.task = mock.Mock(spec=task_manager.TaskManager)
        self.task.context = mock.Mock()
        self.task.shared = False
        self.task.node = self.node
        self.task.driver = self.driver


class CommonFunctionsTestCase(BaseTestCase):
    def test_validate_ok(self):
        self.driver.inspect.validate(self.task)

    def test_get_properties(self):
        res = self.driver.inspect.get_properties()
        self.assertEqual({}, res)

    def test_create_if_enabled(self):
        res = discoverd.DiscoverdInspect.create_if_enabled('driver')
        self.assertIsInstance(res, discoverd.DiscoverdInspect)

    @mock.patch.object(discoverd.LOG, 'info')
    def test_create_if_enabled_disabled(self, warn_mock):
        self.config(enabled=False, group='discoverd')
        res = discoverd.DiscoverdInspect.create_if_enabled('driver')
        self.assertIsNone(res)
        self.assertTrue(warn_mock.called)


@mock.patch.object(eventlet, 'spawn_n', lambda f, *a, **kw: f(*a, **kw))
@mock.patch.object(client, 'introspect')
class InspectHardwareTestCase(BaseTestCase):
    def test_ok(self, mock_introspect):
        self.assertEqual(states.INSPECTING,
                         self.driver.inspect.inspect_hardware(self.task))
        mock_introspect.assert_called_once_with(
            self.node.uuid,
            auth_token=self.task.context.auth_token)

    def test_url(self, mock_introspect):
        self.config(service_url='meow', group='discoverd')
        self.assertEqual(states.INSPECTING,
                         self.driver.inspect.inspect_hardware(self.task))
        mock_introspect.assert_called_once_with(
            self.node.uuid,
            auth_token=self.task.context.auth_token,
            base_url='meow')

    @mock.patch.object(task_manager, 'acquire')
    def test_error(self, mock_acquire, mock_introspect):
        mock_introspect.side_effect = RuntimeError('boom')
        self.driver.inspect.inspect_hardware(self.task)
        mock_introspect.assert_called_once_with(
            self.node.uuid,
            auth_token=self.task.context.auth_token)
        task = mock_acquire.return_value.__enter__.return_value
        self.assertIn('boom', task.node.last_error)
        task.process_event.assert_called_once_with('fail')


@mock.patch.object(keystone, 'get_admin_auth_token', lambda: 'the token')
@mock.patch.object(client, 'get_status')
class CheckStatusTestCase(BaseTestCase):
    def setUp(self):
        super(CheckStatusTestCase, self).setUp()
        self.node.provision_state = states.INSPECTING

    def test_not_inspecting(self, mock_get):
        self.node.provision_state = states.MANAGEABLE
        discoverd._check_status(self.task)
        self.assertFalse(mock_get.called)

    def test_not_discoverd(self, mock_get):
        self.task.driver.inspect = object()
        discoverd._check_status(self.task)
        self.assertFalse(mock_get.called)

    def test_not_finished(self, mock_get):
        mock_get.return_value = {}
        discoverd._check_status(self.task)
        mock_get.assert_called_once_with(self.node.uuid,
                                         auth_token='the token')
        self.assertFalse(self.task.process_event.called)

    def test_exception_ignored(self, mock_get):
        mock_get.side_effect = RuntimeError('boom')
        discoverd._check_status(self.task)
        mock_get.assert_called_once_with(self.node.uuid,
                                         auth_token='the token')
        self.assertFalse(self.task.process_event.called)

    def test_status_ok(self, mock_get):
        mock_get.return_value = {'finished': True}
        discoverd._check_status(self.task)
        mock_get.assert_called_once_with(self.node.uuid,
                                         auth_token='the token')
        self.task.process_event.assert_called_once_with('done')

    def test_status_error(self, mock_get):
        mock_get.return_value = {'error': 'boom'}
        discoverd._check_status(self.task)
        mock_get.assert_called_once_with(self.node.uuid,
                                         auth_token='the token')
        self.task.process_event.assert_called_once_with('fail')
        self.assertIn('boom', self.node.last_error)

    def test_service_url(self, mock_get):
        self.config(service_url='meow', group='discoverd')
        mock_get.return_value = {'finished': True}
        discoverd._check_status(self.task)
        mock_get.assert_called_once_with(self.node.uuid,
                                         auth_token='the token',
                                         base_url='meow')
        self.task.process_event.assert_called_once_with('done')


@mock.patch.object(eventlet.greenthread, 'spawn_n',
                   lambda f, *a, **kw: f(*a, **kw))
@mock.patch.object(ironic_discoverd, '__version_info__', (1, 0, 0))
@mock.patch.object(task_manager, 'acquire', autospec=True)
@mock.patch.object(discoverd, '_check_status', autospec=True)
class PeriodicTaskTestCase(BaseTestCase):
    def test_ok(self, mock_check, mock_acquire):
        mgr = mock.Mock(spec=['iter_nodes'])
        mgr.iter_nodes.return_value = [('1', 'd1'), ('2', 'd2')]
        tasks = [mock.sentinel.task1, mock.sentinel.task2]
        mock_acquire.side_effect = (
            mock.MagicMock(__enter__=mock.Mock(return_value=task))
            for task in tasks
        )
        discoverd.DiscoverdInspect()._periodic_check_result(
            mgr, mock.sentinel.context)
        mock_check.assert_any_call(tasks[0])
        mock_check.assert_any_call(tasks[1])
        self.assertEqual(2, mock_acquire.call_count)

    def test_node_locked(self, mock_check, mock_acquire):
        mgr = mock.Mock(spec=['iter_nodes'])
        mgr.iter_nodes.return_value = [('1', 'd1'), ('2', 'd2')]
        mock_acquire.side_effect = exception.NodeLocked("boom")
        discoverd.DiscoverdInspect()._periodic_check_result(
            mgr, mock.sentinel.context)
        self.assertFalse(mock_check.called)
        self.assertEqual(2, mock_acquire.call_count)
