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
from ironic.drivers import base as drivers_base
from ironic.tests import base


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
            self.assertEqual(2, mock_em.call_count)

    @mock.patch.object(driver_factory.LOG, 'warning', autospec=True)
    def test_driver_duplicated_entry(self, mock_log):
        self.config(enabled_drivers=['fake', 'fake'])
        driver_factory.DriverFactory._init_extension_manager()
        self.assertEqual(
            ['fake'], driver_factory.DriverFactory._extension_manager.names())
        self.assertTrue(mock_log.called)


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
