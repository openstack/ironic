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

import json

import eventlet
import mock

from ironic.common import exception
from ironic.common import raid
from ironic.drivers import base as driver_base
from ironic.tests.unit import base


class FakeVendorInterface(driver_base.VendorInterface):
    def get_properties(self):
        pass

    @driver_base.passthru(['POST'])
    def noexception(self):
        return "Fake"

    @driver_base.driver_passthru(['POST'])
    def driver_noexception(self):
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

    def test_passthru_noexception(self):
        result = self.fvi.noexception()
        self.assertEqual("Fake", result)

    @mock.patch.object(driver_base, 'LOG', autospec=True)
    def test_passthru_ironicexception(self, mock_log):
        self.assertRaises(exception.IronicException,
                          self.fvi.ironicexception, mock.ANY)
        mock_log.exception.assert_called_with(
            mock.ANY, 'ironicexception')

    @mock.patch.object(driver_base, 'LOG', autospec=True)
    def test_passthru_nonironicexception(self, mock_log):
        self.assertRaises(exception.VendorPassthruException,
                          self.fvi.normalexception, mock.ANY)
        mock_log.exception.assert_called_with(
            mock.ANY, 'normalexception')

    def test_passthru_check_func_references(self):
        inst1 = FakeVendorInterface()
        inst2 = FakeVendorInterface()

        self.assertNotEqual(inst1.vendor_routes['noexception']['func'],
                            inst2.vendor_routes['noexception']['func'])
        self.assertNotEqual(inst1.driver_routes['driver_noexception']['func'],
                            inst2.driver_routes['driver_noexception']['func'])


@mock.patch.object(eventlet.greenthread, 'spawn_n', autospec=True,
                   side_effect=lambda func, *args, **kw: func(*args, **kw))
class DriverPeriodicTaskTestCase(base.TestCase):
    def test(self, spawn_mock):
        method_mock = mock.MagicMock(spec_set=[])
        function_mock = mock.MagicMock(spec_set=[])

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
        self.assertEqual('ironic.tests.unit.drivers.test_base.method',
                         obj.method._periodic_name)
        self.assertEqual('ironic.tests.unit.drivers.test_base.function',
                         function._periodic_name)

        obj.method(1, bar=2)
        method_mock.assert_called_once_with(1, bar=2)
        self.assertEqual(1, spawn_mock.call_count)
        function()
        function_mock.assert_called_once_with()
        self.assertEqual(1, spawn_mock.call_count)


class CleanStepTestCase(base.TestCase):
    def test_get_and_execute_clean_steps(self):
        # Create a fake Driver class, create some clean steps, make sure
        # they are listed correctly, and attempt to execute one of them

        method_mock = mock.MagicMock(spec_set=[])
        task_mock = mock.MagicMock(spec_set=[])

        class TestClass(driver_base.BaseInterface):
            interface_type = 'test'

            @driver_base.clean_step(priority=0)
            def zap_method(self, task):
                pass

            @driver_base.clean_step(priority=10, abortable=True)
            def clean_method(self, task):
                method_mock(task)

            def not_clean_method(self, task):
                pass

        class TestClass2(driver_base.BaseInterface):
            interface_type = 'test2'

            @driver_base.clean_step(priority=0)
            def zap_method2(self, task):
                pass

            @driver_base.clean_step(priority=20, abortable=True)
            def clean_method2(self, task):
                method_mock(task)

            def not_clean_method2(self, task):
                pass

        obj = TestClass()
        obj2 = TestClass2()

        self.assertEqual(2, len(obj.get_clean_steps(task_mock)))
        # Ensure the steps look correct
        self.assertEqual(10, obj.get_clean_steps(task_mock)[0]['priority'])
        self.assertTrue(obj.get_clean_steps(task_mock)[0]['abortable'])
        self.assertEqual('test', obj.get_clean_steps(
            task_mock)[0]['interface'])
        self.assertEqual('clean_method', obj.get_clean_steps(
            task_mock)[0]['step'])
        self.assertEqual(0, obj.get_clean_steps(task_mock)[1]['priority'])
        self.assertFalse(obj.get_clean_steps(task_mock)[1]['abortable'])
        self.assertEqual('test', obj.get_clean_steps(
            task_mock)[1]['interface'])
        self.assertEqual('zap_method', obj.get_clean_steps(
            task_mock)[1]['step'])

        # Ensure the second obj get different clean steps
        self.assertEqual(2, len(obj2.get_clean_steps(task_mock)))
        # Ensure the steps look correct
        self.assertEqual(20, obj2.get_clean_steps(task_mock)[0]['priority'])
        self.assertTrue(obj2.get_clean_steps(task_mock)[0]['abortable'])
        self.assertEqual('test2', obj2.get_clean_steps(
            task_mock)[0]['interface'])
        self.assertEqual('clean_method2', obj2.get_clean_steps(
            task_mock)[0]['step'])
        self.assertEqual(0, obj2.get_clean_steps(task_mock)[1]['priority'])
        self.assertFalse(obj.get_clean_steps(task_mock)[1]['abortable'])
        self.assertEqual('test2', obj2.get_clean_steps(
            task_mock)[1]['interface'])
        self.assertEqual('zap_method2', obj2.get_clean_steps(
            task_mock)[1]['step'])

        # Ensure we can execute the function.
        obj.execute_clean_step(task_mock, obj.get_clean_steps(task_mock)[0])
        method_mock.assert_called_once_with(task_mock)


class MyRAIDInterface(driver_base.RAIDInterface):

    def create_configuration(self, task):
        pass

    def delete_configuration(self, task):
        pass


class RAIDInterfaceTestCase(base.TestCase):

    @mock.patch.object(driver_base.RAIDInterface, 'validate_raid_config',
                       autospec=True)
    def test_validate(self, validate_raid_config_mock):
        raid_interface = MyRAIDInterface()
        node_mock = mock.MagicMock(target_raid_config='some_raid_config')
        task_mock = mock.MagicMock(node=node_mock)

        raid_interface.validate(task_mock)

        validate_raid_config_mock.assert_called_once_with(
            raid_interface, task_mock, 'some_raid_config')

    @mock.patch.object(driver_base.RAIDInterface, 'validate_raid_config',
                       autospec=True)
    def test_validate_no_target_raid_config(self, validate_raid_config_mock):
        raid_interface = MyRAIDInterface()
        node_mock = mock.MagicMock(target_raid_config={})
        task_mock = mock.MagicMock(node=node_mock)

        raid_interface.validate(task_mock)

        self.assertFalse(validate_raid_config_mock.called)

    @mock.patch.object(raid, 'validate_configuration', autospec=True)
    def test_validate_raid_config(self, common_validate_mock):
        with open(driver_base.RAID_CONFIG_SCHEMA, 'r') as raid_schema_fobj:
            raid_schema = json.load(raid_schema_fobj)
        raid_interface = MyRAIDInterface()

        raid_interface.validate_raid_config('task', 'some_raid_config')

        common_validate_mock.assert_called_once_with(
            'some_raid_config', raid_schema)

    @mock.patch.object(raid, 'get_logical_disk_properties',
                       autospec=True)
    def test_get_logical_disk_properties(self, get_properties_mock):
        with open(driver_base.RAID_CONFIG_SCHEMA, 'r') as raid_schema_fobj:
            raid_schema = json.load(raid_schema_fobj)
        raid_interface = MyRAIDInterface()
        raid_interface.get_logical_disk_properties()
        get_properties_mock.assert_called_once_with(raid_schema)
