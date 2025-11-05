#
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
"""Unit tests for ``ironic.networking.driver_factory``."""

from unittest import mock

from oslo_config import cfg

from ironic.common import exception
from ironic.networking.switch_drivers import driver_factory
from ironic import tests as tests_root


CONF = cfg.CONF


class BaseSwitchDriverFactoryTestCase(tests_root.base.TestCase):
    """Test behaviour common to switch driver factory classes."""

    def setUp(self):
        super(BaseSwitchDriverFactoryTestCase, self).setUp()
        self.factory = driver_factory.BaseSwitchDriverFactory()

    def test_set_enabled_drivers(self):
        self.config(group='ironic_networking', enabled_switch_drivers=['noop'])

        self.factory._set_enabled_drivers()

        self.assertEqual(['noop'], self.factory._enabled_driver_list)

    def test_set_enabled_drivers_with_duplicates(self):
        self.config(group='ironic_networking',
                    enabled_switch_drivers=['noop', 'noop'])

        exc = self.assertRaises(exception.ConfigInvalid,
                                self.factory._set_enabled_drivers)
        self.assertIn('noop', str(exc))
        self.assertIn('duplicated', str(exc))

    def test_set_enabled_drivers_with_empty_value(self):
        self.config(group='ironic_networking',
                    enabled_switch_drivers=['', 'noop'])

        exc = self.assertRaises(exception.ConfigInvalid,
                                self.factory._set_enabled_drivers)
        self.assertIn('empty', str(exc))
        self.assertIn('enabled_switch_drivers', str(exc))

    def test_init_extension_manager_no_enabled_drivers(self):
        self.factory._enabled_driver_list = []

        with mock.patch.object(
            driver_factory.LOG, 'info', autospec=True
        ) as mock_info:
            self.factory._init_extension_manager()

        mock_info.assert_called_once()

    @mock.patch('stevedore.NamedExtensionManager', autospec=True)
    def test_init_extension_manager_handles_runtime_error(
            self, mock_named_ext_mgr):
        # Reset extension manager state
        type(self.factory)._extension_manager = None
        type(self.factory)._enabled_driver_list = None
        self.config(group='ironic_networking', enabled_switch_drivers=['noop'])

        mock_named_ext_mgr.side_effect = RuntimeError(
            'No suitable drivers found')

        with mock.patch.object(
            driver_factory.LOG, 'warning', autospec=True
        ) as mock_warn:
            type(self.factory)._init_extension_manager()

        mock_warn.assert_called_once()
        self.assertIsNone(type(self.factory)._extension_manager)

    @mock.patch('stevedore.NamedExtensionManager', autospec=True)
    def test_init_extension_manager_unexpected_runtime_error(
            self, mock_named_ext_mgr):
        # Reset extension manager state
        type(self.factory)._extension_manager = None
        type(self.factory)._enabled_driver_list = None
        self.config(group='ironic_networking', enabled_switch_drivers=['noop'])

        mock_named_ext_mgr.side_effect = RuntimeError('boom')

        self.assertRaises(RuntimeError,
                          type(self.factory)._init_extension_manager)


class FactoryHelpersTestCase(tests_root.base.TestCase):
    """Tests for module-level helper functions."""

    def test_warn_if_unsupported(self):
        fake_extension = mock.Mock()
        fake_extension.obj.supported = False
        fake_extension.name = 'unsupported'

        with mock.patch.object(
            driver_factory.LOG, 'warning', autospec=True
        ) as mock_warn:
            driver_factory._warn_if_unsupported(fake_extension)

        mock_warn.assert_called_once()

    def test_warn_if_supported(self):
        fake_extension = mock.Mock()
        fake_extension.obj.supported = True

        with mock.patch.object(
            driver_factory.LOG, 'warning', autospec=True
        ) as mock_warn:
            driver_factory._warn_if_unsupported(fake_extension)

        mock_warn.assert_not_called()


class GlobalFactoryHelpersTestCase(tests_root.base.TestCase):
    """Tests for global helper functions providing factory access."""

    def setUp(self):
        super(GlobalFactoryHelpersTestCase, self).setUp()
        # Save and restore the global factory singleton
        original_factory = driver_factory._switch_driver_factory
        self.addCleanup(setattr, driver_factory, '_switch_driver_factory',
                        original_factory)
        driver_factory._switch_driver_factory = None

    def test_get_switch_driver_factory_singleton(self):
        factory1 = driver_factory.get_switch_driver_factory()
        factory2 = driver_factory.get_switch_driver_factory()
        self.assertIs(factory1, factory2)

    def test_get_switch_driver(self):
        factory = driver_factory.get_switch_driver_factory()

        with mock.patch.object(
            factory, 'get_driver', return_value='driver', autospec=True
        ) as mock_get:
            result = driver_factory.get_switch_driver('noop')

        mock_get.assert_called_once_with('noop')
        self.assertEqual('driver', result)

    def test_list_switch_drivers(self):
        factory = driver_factory.get_switch_driver_factory()

        with mock.patch.object(
            type(factory), 'names', new_callable=mock.PropertyMock,
            return_value=['noop']
        ):
            result = driver_factory.list_switch_drivers()

        self.assertEqual(['noop'], result)

    def test_switch_drivers(self):
        factory = driver_factory.get_switch_driver_factory()

        with mock.patch.object(
            factory, 'items', return_value=[('noop', 'driver')],
            autospec=True
        ):
            result = driver_factory.switch_drivers()

        self.assertEqual({'noop': 'driver'}, result)
