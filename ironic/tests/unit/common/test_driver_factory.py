# coding=utf-8

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
from stevedore import dispatch

from ironic.common import driver_factory
from ironic.common import exception
from ironic.conductor import task_manager
from ironic.drivers import base as drivers_base
from ironic.tests import base
from ironic.tests.unit.db import base as db_base
from ironic.tests.unit.objects import utils as obj_utils


class FakeEp(object):
    name = 'fake'


class DriverLoadTestCase(base.TestCase):

    def setUp(self):
        super(DriverLoadTestCase, self).setUp()
        driver_factory.DriverFactory._extension_manager = None

    def _fake_init_name_err(self, *args, **kwargs):
        kwargs['on_load_failure_callback'](None, FakeEp, NameError('aaa'))

    def _fake_init_driver_err(self, *args, **kwargs):
        kwargs['on_load_failure_callback'](None, FakeEp,
                                           exception.DriverLoadError(
                                               driver='aaa', reason='bbb'))

    def test_driver_load_error_if_driver_enabled(self):
        self.config(enabled_drivers=['fake'])
        with mock.patch.object(dispatch.NameDispatchExtensionManager,
                               '__init__', self._fake_init_driver_err):
            self.assertRaises(
                exception.DriverLoadError,
                driver_factory.DriverFactory._init_extension_manager)

    def test_wrap_in_driver_load_error_if_driver_enabled(self):
        self.config(enabled_drivers=['fake'])
        with mock.patch.object(dispatch.NameDispatchExtensionManager,
                               '__init__', self._fake_init_name_err):
            self.assertRaises(
                exception.DriverLoadError,
                driver_factory.DriverFactory._init_extension_manager)

    @mock.patch.object(dispatch.NameDispatchExtensionManager, 'names',
                       autospec=True)
    def test_no_driver_load_error_if_driver_disabled(self, mock_em):
        self.config(enabled_drivers=[])
        with mock.patch.object(dispatch.NameDispatchExtensionManager,
                               '__init__', self._fake_init_driver_err):
            driver_factory.DriverFactory._init_extension_manager()
            self.assertEqual(3, mock_em.call_count)

    @mock.patch.object(driver_factory.LOG, 'warning', autospec=True)
    def test_driver_duplicated_entry(self, mock_log):
        self.config(enabled_drivers=['fake', 'fake'])
        driver_factory.DriverFactory._init_extension_manager()
        self.assertEqual(
            ['fake'], driver_factory.DriverFactory._extension_manager.names())
        self.assertTrue(mock_log.called)

    @mock.patch.object(driver_factory, '_warn_if_unsupported')
    def test_driver_init_checks_unsupported(self, mock_warn):
        self.config(enabled_drivers=['fake'])
        driver_factory.DriverFactory._init_extension_manager()
        self.assertEqual(
            ['fake'], driver_factory.DriverFactory._extension_manager.names())
        self.assertTrue(mock_warn.called)


class WarnUnsupportedDriversTestCase(base.TestCase):
    @mock.patch.object(driver_factory.LOG, 'warning', autospec=True)
    def _test__warn_if_unsupported(self, supported, mock_log):
        ext = mock.Mock()
        ext.obj = mock.Mock()
        ext.obj.supported = supported
        driver_factory._warn_if_unsupported(ext)
        if supported:
            self.assertFalse(mock_log.called)
        else:
            self.assertTrue(mock_log.called)

    def test__warn_if_unsupported_with_supported(self):
        self._test__warn_if_unsupported(True)

    def test__warn_if_unsupported_with_unsupported(self):
        self._test__warn_if_unsupported(False)


class GetDriverTestCase(base.TestCase):
    def setUp(self):
        super(GetDriverTestCase, self).setUp()
        driver_factory.DriverFactory._extension_manager = None
        self.config(enabled_drivers=['fake'])

    def test_get_driver_known(self):
        driver = driver_factory.get_driver('fake')
        self.assertIsInstance(driver, drivers_base.BaseDriver)

    def test_get_driver_unknown(self):
        self.assertRaises(exception.DriverNotFound,
                          driver_factory.get_driver, 'unknown_driver')


class NetworkInterfaceFactoryTestCase(db_base.DbTestCase):
    def setUp(self):
        super(NetworkInterfaceFactoryTestCase, self).setUp()
        driver_factory.DriverFactory._extension_manager = None
        driver_factory.NetworkInterfaceFactory._extension_manager = None
        self.config(enabled_drivers=['fake'])

    @mock.patch.object(driver_factory, '_warn_if_unsupported')
    def test_build_driver_for_task(self, mock_warn):
        # flat, neutron, and noop network interfaces are enabled in base test
        # case
        factory = driver_factory.NetworkInterfaceFactory
        node = obj_utils.create_test_node(self.context, driver='fake',
                                          network_interface='flat')
        with task_manager.acquire(self.context, node.id) as task:
            extension_mgr = factory._extension_manager
            self.assertIn('flat', extension_mgr)
            self.assertIn('neutron', extension_mgr)
            self.assertIn('noop', extension_mgr)
            self.assertEqual(extension_mgr['flat'].obj, task.driver.network)
        self.assertEqual('ironic.hardware.interfaces.network',
                         factory._entrypoint_name)
        self.assertEqual(['flat', 'neutron', 'noop'],
                         sorted(factory._enabled_driver_list))
        # NOTE(jroll) 4 checks, one for the driver we're building and
        # one for each of the 3 network interfaces
        self.assertEqual(4, mock_warn.call_count)

    def test_build_driver_for_task_default_is_none(self):
        # flat, neutron, and noop network interfaces are enabled in base test
        # case
        factory = driver_factory.NetworkInterfaceFactory
        self.config(dhcp_provider='none', group='dhcp')
        node = obj_utils.create_test_node(self.context, driver='fake')
        with task_manager.acquire(self.context, node.id) as task:
            extension_mgr = factory._extension_manager
            self.assertIn('flat', extension_mgr)
            self.assertIn('neutron', extension_mgr)
            self.assertIn('noop', extension_mgr)
            self.assertEqual(extension_mgr['noop'].obj, task.driver.network)

    def test_build_driver_for_task_default_network_interface_is_set(self):
        # flat, neutron, and noop network interfaces are enabled in base test
        # case
        factory = driver_factory.NetworkInterfaceFactory
        self.config(dhcp_provider='none', group='dhcp')
        self.config(default_network_interface='flat')
        node = obj_utils.create_test_node(self.context, driver='fake')
        with task_manager.acquire(self.context, node.id) as task:
            extension_mgr = factory._extension_manager
            self.assertIn('flat', extension_mgr)
            self.assertIn('neutron', extension_mgr)
            self.assertIn('noop', extension_mgr)
            self.assertEqual(extension_mgr['flat'].obj, task.driver.network)

    def test_build_driver_for_task_default_is_flat(self):
        # flat, neutron, and noop network interfaces are enabled in base test
        # case
        factory = driver_factory.NetworkInterfaceFactory
        node = obj_utils.create_test_node(self.context, driver='fake')
        with task_manager.acquire(self.context, node.id) as task:
            extension_mgr = factory._extension_manager
            self.assertIn('flat', extension_mgr)
            self.assertIn('neutron', extension_mgr)
            self.assertIn('noop', extension_mgr)
            self.assertEqual(extension_mgr['flat'].obj, task.driver.network)

    def test_build_driver_for_task_unknown_network_interface(self):
        node = obj_utils.create_test_node(self.context, driver='fake',
                                          network_interface='meow')
        self.assertRaises(exception.DriverNotFoundInEntrypoint,
                          task_manager.acquire, self.context, node.id)


class NewDriverFactory(driver_factory.BaseDriverFactory):
    _entrypoint_name = 'woof'


class NewFactoryTestCase(db_base.DbTestCase):
    def test_new_driver_factory_unknown_entrypoint(self):
        factory = NewDriverFactory()
        self.assertEqual('woof', factory._entrypoint_name)
        self.assertEqual([], factory._enabled_driver_list)
