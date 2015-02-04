# Copyright 2014 Cisco Systems, Inc.
# All Rights Reserved.
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

import eventlet
import mock

from ironic.common import exception
from ironic.drivers import base as driver_base
from ironic.tests import base


class FakeVendorInterface(driver_base.VendorInterface):
    def get_properties(self):
        pass

    @driver_base.passthru(['POST'])
    def noexception(self):
        return "Fake"

    @driver_base.passthru(['POST'])
    def ironicexception(self):
        raise exception.IronicException("Fake!")

    @driver_base.passthru(['POST'])
    def normalexception(self):
        raise Exception("Fake!")

    def validate(self, task, **kwargs):
        pass

    def driver_validate(self, **kwargs):
        pass


class PassthruDecoratorTestCase(base.TestCase):

    def setUp(self):
        super(PassthruDecoratorTestCase, self).setUp()
        self.fvi = FakeVendorInterface()
        driver_base.LOG = mock.Mock()

    def test_passthru_noexception(self):
        result = self.fvi.noexception()
        self.assertEqual("Fake", result)

    def test_passthru_ironicexception(self):
        self.assertRaises(exception.IronicException,
            self.fvi.ironicexception, mock.ANY)
        driver_base.LOG.exception.assert_called_with(
            mock.ANY, 'ironicexception')

    def test_passthru_nonironicexception(self):
        self.assertRaises(exception.VendorPassthruException,
            self.fvi.normalexception, mock.ANY)
        driver_base.LOG.exception.assert_called_with(
            mock.ANY, 'normalexception')


@mock.patch.object(eventlet.greenthread, 'spawn_n',
                   side_effect=lambda func, *args, **kw: func(*args, **kw))
class DriverPeriodicTaskTestCase(base.TestCase):
    def test(self, spawn_mock):
        method_mock = mock.Mock()
        function_mock = mock.Mock()

        class TestClass(object):
            @driver_base.driver_periodic_task(spacing=42)
            def method(self, foo, bar=None):
                method_mock(foo, bar=bar)

        @driver_base.driver_periodic_task(spacing=100, parallel=False)
        def function():
            function_mock()

        obj = TestClass()
        self.assertEqual(42, obj.method._periodic_spacing)
        self.assertTrue(obj.method._periodic_task)
        self.assertEqual('ironic.tests.drivers.test_base.method',
                         obj.method._periodic_name)
        self.assertEqual('ironic.tests.drivers.test_base.function',
                         function._periodic_name)

        obj.method(1, bar=2)
        method_mock.assert_called_once_with(1, bar=2)
        self.assertEqual(1, spawn_mock.call_count)
        function()
        function_mock.assert_called_once_with()
        self.assertEqual(1, spawn_mock.call_count)
