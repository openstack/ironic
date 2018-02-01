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

import mock
import stevedore

from ironic.common import driver_factory
from ironic.common import exception
from ironic.common import raid
from ironic.drivers import base as driver_base
from ironic.drivers.modules import fake
from ironic.tests import base


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

    @driver_base.passthru(['POST'], require_exclusive_lock=False)
    def shared_task(self):
        return "shared fake"

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

    def test_passthru_shared_task_metadata(self):
        self.assertIn('require_exclusive_lock',
                      self.fvi.shared_task._vendor_metadata[1])
        self.assertFalse(
            self.fvi.shared_task._vendor_metadata[1]['require_exclusive_lock'])

    def test_passthru_exclusive_task_metadata(self):
        self.assertIn('require_exclusive_lock',
                      self.fvi.noexception._vendor_metadata[1])
        self.assertTrue(
            self.fvi.noexception._vendor_metadata[1]['require_exclusive_lock'])

    def test_passthru_check_func_references(self):
        inst1 = FakeVendorInterface()
        inst2 = FakeVendorInterface()

        self.assertNotEqual(inst1.vendor_routes['noexception']['func'],
                            inst2.vendor_routes['noexception']['func'])
        self.assertNotEqual(inst1.driver_routes['driver_noexception']['func'],
                            inst2.driver_routes['driver_noexception']['func'])


class CleanStepDecoratorTestCase(base.TestCase):

    def setUp(self):
        super(CleanStepDecoratorTestCase, self).setUp()
        method_mock = mock.MagicMock()
        del method_mock._is_clean_step
        del method_mock._clean_step_priority
        del method_mock._clean_step_abortable
        del method_mock._clean_step_argsinfo
        self.method = method_mock

    def test__validate_argsinfo(self):
        # None, empty dict
        driver_base._validate_argsinfo(None)
        driver_base._validate_argsinfo({})

        # Only description specified
        driver_base._validate_argsinfo({'arg1': {'description': 'desc1'}})

        # Multiple args
        driver_base._validate_argsinfo({'arg1': {'description': 'desc1',
                                                 'required': True},
                                        'arg2': {'description': 'desc2'}})

    def test__validate_argsinfo_not_dict(self):
        self.assertRaisesRegex(exception.InvalidParameterValue,
                               'argsinfo.+dictionary',
                               driver_base._validate_argsinfo, 'not-a-dict')

    def test__validate_argsinfo_arg_not_dict(self):
        self.assertRaisesRegex(exception.InvalidParameterValue,
                               'Argument.+dictionary',
                               driver_base._validate_argsinfo,
                               {'arg1': 'not-a-dict'})

    def test__validate_argsinfo_arg_empty_dict(self):
        self.assertRaisesRegex(exception.InvalidParameterValue,
                               'description',
                               driver_base._validate_argsinfo,
                               {'arg1': {}})

    def test__validate_argsinfo_arg_missing_description(self):
        self.assertRaisesRegex(exception.InvalidParameterValue,
                               'description',
                               driver_base._validate_argsinfo,
                               {'arg1': {'required': True}})

    def test__validate_argsinfo_arg_description_invalid(self):
        self.assertRaisesRegex(exception.InvalidParameterValue,
                               'string',
                               driver_base._validate_argsinfo,
                               {'arg1': {'description': True}})

    def test__validate_argsinfo_arg_required_invalid(self):
        self.assertRaisesRegex(exception.InvalidParameterValue,
                               'Boolean',
                               driver_base._validate_argsinfo,
                               {'arg1': {'description': 'desc1',
                                         'required': 'maybe'}})

    def test__validate_argsinfo_arg_unknown_key(self):
        self.assertRaisesRegex(exception.InvalidParameterValue,
                               'invalid',
                               driver_base._validate_argsinfo,
                               {'arg1': {'description': 'desc1',
                                         'unknown': 'bad'}})

    def test_clean_step_priority_only(self):
        d = driver_base.clean_step(priority=10)
        d(self.method)
        self.assertTrue(self.method._is_clean_step)
        self.assertEqual(10, self.method._clean_step_priority)
        self.assertFalse(self.method._clean_step_abortable)
        self.assertIsNone(self.method._clean_step_argsinfo)

    def test_clean_step_all_args(self):
        argsinfo = {'arg1': {'description': 'desc1',
                             'required': True}}
        d = driver_base.clean_step(priority=0, abortable=True,
                                   argsinfo=argsinfo)
        d(self.method)
        self.assertTrue(self.method._is_clean_step)
        self.assertEqual(0, self.method._clean_step_priority)
        self.assertTrue(self.method._clean_step_abortable)
        self.assertEqual(argsinfo, self.method._clean_step_argsinfo)

    def test_clean_step_bad_priority(self):
        d = driver_base.clean_step(priority='hi')
        self.assertRaisesRegex(exception.InvalidParameterValue, 'priority',
                               d, self.method)
        self.assertTrue(self.method._is_clean_step)
        self.assertFalse(hasattr(self.method, '_clean_step_priority'))
        self.assertFalse(hasattr(self.method, '_clean_step_abortable'))
        self.assertFalse(hasattr(self.method, '_clean_step_argsinfo'))

    def test_clean_step_bad_abortable(self):
        d = driver_base.clean_step(priority=0, abortable='blue')
        self.assertRaisesRegex(exception.InvalidParameterValue, 'abortable',
                               d, self.method)
        self.assertTrue(self.method._is_clean_step)
        self.assertEqual(0, self.method._clean_step_priority)
        self.assertFalse(hasattr(self.method, '_clean_step_abortable'))
        self.assertFalse(hasattr(self.method, '_clean_step_argsinfo'))

    @mock.patch.object(driver_base, '_validate_argsinfo', spec_set=True,
                       autospec=True)
    def test_clean_step_bad_argsinfo(self, mock_valid):
        mock_valid.side_effect = exception.InvalidParameterValue('bad')
        d = driver_base.clean_step(priority=0, argsinfo=100)
        self.assertRaises(exception.InvalidParameterValue, d, self.method)
        self.assertTrue(self.method._is_clean_step)
        self.assertEqual(0, self.method._clean_step_priority)
        self.assertFalse(self.method._clean_step_abortable)
        self.assertFalse(hasattr(self.method, '_clean_step_argsinfo'))


class CleanStepTestCase(base.TestCase):
    def test_get_and_execute_clean_steps(self):
        # Create a fake Driver class, create some clean steps, make sure
        # they are listed correctly, and attempt to execute one of them

        method_mock = mock.MagicMock(spec_set=[])
        method_args_mock = mock.MagicMock(spec_set=[])
        task_mock = mock.MagicMock(spec_set=[])

        class BaseTestClass(driver_base.BaseInterface):
            def get_properties(self):
                return {}

            def validate(self, task):
                pass

        class TestClass(BaseTestClass):
            interface_type = 'test'

            @driver_base.clean_step(priority=0)
            def manual_method(self, task):
                pass

            @driver_base.clean_step(priority=10, abortable=True)
            def automated_method(self, task):
                method_mock(task)

            def not_clean_method(self, task):
                pass

        class TestClass2(BaseTestClass):
            interface_type = 'test2'

            @driver_base.clean_step(priority=0)
            def manual_method2(self, task):
                pass

            @driver_base.clean_step(priority=20, abortable=True)
            def automated_method2(self, task):
                method_mock(task)

            def not_clean_method2(self, task):
                pass

        class TestClass3(BaseTestClass):
            interface_type = 'test3'

            @driver_base.clean_step(priority=0, abortable=True, argsinfo={
                                    'arg1': {'description': 'desc1',
                                             'required': True}})
            def manual_method3(self, task, **kwargs):
                method_args_mock(task, **kwargs)

            @driver_base.clean_step(priority=15, argsinfo={
                                    'arg10': {'description': 'desc10'}})
            def automated_method3(self, task, **kwargs):
                pass

            def not_clean_method3(self, task):
                pass

        obj = TestClass()
        obj2 = TestClass2()
        obj3 = TestClass3()

        self.assertEqual(2, len(obj.get_clean_steps(task_mock)))
        # Ensure the steps look correct
        self.assertEqual(10, obj.get_clean_steps(task_mock)[0]['priority'])
        self.assertTrue(obj.get_clean_steps(task_mock)[0]['abortable'])
        self.assertEqual('test', obj.get_clean_steps(
            task_mock)[0]['interface'])
        self.assertEqual('automated_method', obj.get_clean_steps(
            task_mock)[0]['step'])
        self.assertEqual(0, obj.get_clean_steps(task_mock)[1]['priority'])
        self.assertFalse(obj.get_clean_steps(task_mock)[1]['abortable'])
        self.assertEqual('test', obj.get_clean_steps(
            task_mock)[1]['interface'])
        self.assertEqual('manual_method', obj.get_clean_steps(
            task_mock)[1]['step'])

        # Ensure the second obj get different clean steps
        self.assertEqual(2, len(obj2.get_clean_steps(task_mock)))
        # Ensure the steps look correct
        self.assertEqual(20, obj2.get_clean_steps(task_mock)[0]['priority'])
        self.assertTrue(obj2.get_clean_steps(task_mock)[0]['abortable'])
        self.assertEqual('test2', obj2.get_clean_steps(
            task_mock)[0]['interface'])
        self.assertEqual('automated_method2', obj2.get_clean_steps(
            task_mock)[0]['step'])
        self.assertEqual(0, obj2.get_clean_steps(task_mock)[1]['priority'])
        self.assertFalse(obj2.get_clean_steps(task_mock)[1]['abortable'])
        self.assertEqual('test2', obj2.get_clean_steps(
            task_mock)[1]['interface'])
        self.assertEqual('manual_method2', obj2.get_clean_steps(
            task_mock)[1]['step'])
        self.assertIsNone(obj2.get_clean_steps(task_mock)[0]['argsinfo'])

        # Ensure the third obj has different clean steps
        self.assertEqual(2, len(obj3.get_clean_steps(task_mock)))
        self.assertEqual(15, obj3.get_clean_steps(task_mock)[0]['priority'])
        self.assertFalse(obj3.get_clean_steps(task_mock)[0]['abortable'])
        self.assertEqual('test3', obj3.get_clean_steps(
            task_mock)[0]['interface'])
        self.assertEqual('automated_method3', obj3.get_clean_steps(
            task_mock)[0]['step'])
        self.assertEqual({'arg10': {'description': 'desc10'}},
                         obj3.get_clean_steps(task_mock)[0]['argsinfo'])
        self.assertEqual(0, obj3.get_clean_steps(task_mock)[1]['priority'])
        self.assertTrue(obj3.get_clean_steps(task_mock)[1]['abortable'])
        self.assertEqual(obj3.interface_type, obj3.get_clean_steps(
            task_mock)[1]['interface'])
        self.assertEqual('manual_method3', obj3.get_clean_steps(
            task_mock)[1]['step'])
        self.assertEqual({'arg1': {'description': 'desc1', 'required': True}},
                         obj3.get_clean_steps(task_mock)[1]['argsinfo'])

        # Ensure we can execute the function.
        obj.execute_clean_step(task_mock, obj.get_clean_steps(task_mock)[0])
        method_mock.assert_called_once_with(task_mock)

        args = {'arg1': 'val1'}
        clean_step = {'interface': 'test3', 'step': 'manual_method3',
                      'args': args}
        obj3.execute_clean_step(task_mock, clean_step)
        method_args_mock.assert_called_once_with(task_mock, **args)


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


class TestDeployInterface(base.TestCase):
    @mock.patch.object(driver_base.LOG, 'warning', autospec=True)
    def test_warning_on_heartbeat(self, mock_log):
        # NOTE(dtantsur): FakeDeploy does not override heartbeat
        deploy = fake.FakeDeploy()
        deploy.heartbeat(mock.Mock(node=mock.Mock(uuid='uuid',
                                                  driver='driver')),
                         'url', '3.2.0')
        self.assertTrue(mock_log.called)


class TestManagementInterface(base.TestCase):

    def test_inject_nmi_default_impl(self):
        management = fake.FakeManagement()
        task_mock = mock.MagicMock(spec_set=['node'])

        self.assertRaises(exception.UnsupportedDriverExtension,
                          management.inject_nmi, task_mock)


class TestBaseDriver(base.TestCase):

    def test_class_variables_immutable(self):
        # Test to make sure that our *_interfaces variables in the class don't
        # get modified by a child class
        self.assertEqual(('deploy', 'power'),
                         driver_base.BaseDriver.core_interfaces)
        self.assertEqual(('boot', 'console', 'inspect', 'management', 'raid'),
                         driver_base.BaseDriver.standard_interfaces)
        # Ensure that instantiating an instance of a derived class does not
        # change our variables.
        driver_base.BareDriver()

        self.assertEqual(('deploy', 'power'),
                         driver_base.BaseDriver.core_interfaces)
        self.assertEqual(('boot', 'console', 'inspect', 'management', 'raid'),
                         driver_base.BaseDriver.standard_interfaces)


class TestBareDriver(base.TestCase):

    def test_class_variables_immutable(self):
        # Test to make sure that our *_interfaces variables in the class don't
        # get modified by a child class
        self.assertEqual(('deploy', 'power', 'network'),
                         driver_base.BareDriver.core_interfaces)
        self.assertEqual(
            ('boot', 'console', 'inspect', 'management', 'raid',
             'rescue', 'storage'),
            driver_base.BareDriver.standard_interfaces
        )


class TestToHardwareType(base.TestCase):
    def setUp(self):
        super(TestToHardwareType, self).setUp()
        self.driver_classes = list(
            driver_factory.classic_drivers_to_migrate().values())
        self.existing_ifaces = {}
        for iface in driver_base.ALL_INTERFACES:
            self.existing_ifaces[iface] = stevedore.ExtensionManager(
                'ironic.hardware.interfaces.%s' % iface,
                invoke_on_load=False).names()
        self.hardware_types = stevedore.ExtensionManager(
            'ironic.hardware.types', invoke_on_load=False).names()
        # These are the interfaces that don't have a no-op version
        self.mandatory_interfaces = ['boot', 'deploy', 'management', 'power']

    def test_to_hardware_type_returns_hardware_type(self):
        for driver in self.driver_classes:
            try:
                hw_type = driver.to_hardware_type()[0]
            except NotImplementedError:
                continue
            except KeyError:
                self.fail('%s does not return a tuple' % driver)

            self.assertIn(hw_type, self.hardware_types,
                          '%s returns unknown hardware type %s' %
                          (driver, hw_type))

    def test_to_hardware_type_returns_existing_interfaces(self):
        self.config(enabled=False, group='inspector')
        # Check that all defined implementations of to_hardware_type
        # contain only existing interface types
        for driver in self.driver_classes:
            try:
                delta = driver.to_hardware_type()[1]
            except Exception:
                continue  # covered by other tests
            for iface, value in delta.items():
                self.assertIn(iface, self.existing_ifaces,
                              '%s returns unknown interface %s' %
                              (driver, iface))
                self.assertIn(value, self.existing_ifaces[iface],
                              '%s returns unknown %s interface %s' %
                              (driver, iface, value))

    def test_to_hardware_type_returns_existing_interfaces_inspector(self):
        self.config(enabled=True, group='inspector')
        # Check that all defined implementations of to_hardware_type
        # contain only existing interface types
        for driver in self.driver_classes:
            try:
                delta = driver.to_hardware_type()[1]
            except Exception:
                continue  # covered by other tests
            for iface, value in delta.items():
                self.assertIn(iface, self.existing_ifaces,
                              '%s returns unknown interface %s' %
                              (driver, iface))
                self.assertIn(value, self.existing_ifaces[iface],
                              '%s returns unknown %s interface %s' %
                              (driver, iface, value))

    def test_to_hardware_type_mandatory_interfaces(self):
        for driver in self.driver_classes:
            try:
                delta = driver.to_hardware_type()[1]
            except Exception:
                continue  # covered by other tests
            for iface in self.mandatory_interfaces:
                self.assertIn(iface, delta,
                              '%s does not return mandatory interface %s' %
                              (driver, iface))

    def test_to_hardware_type_for_all_in_tree_drivers(self):
        missing = set()
        for driver in self.driver_classes:
            # We don't want to test out-of-tree drivers installed locally
            if not driver.__module__.startswith('ironic.'):
                continue
            try:
                driver.to_hardware_type()
            except NotImplementedError:
                missing.add(driver.__name__)

        if missing:
            self.fail('to_hardware_type not implemented for %s' %
                      ', '.join(missing))

    def test_to_hardware_type_boot_deploy(self):
        for driver in self.driver_classes:
            # We don't want to test out-of-tree drivers installed locally
            if not driver.__module__.startswith('ironic.'):
                continue

            try:
                delta = driver.to_hardware_type()[1]
                boot = delta['boot']
                deploy = delta['deploy']
            except NotImplementedError:
                continue  # covered by other tests

            name = driver.__name__.lower()
            # Try to guess the correct values for boot and deploy based on our
            # naming schema
            if 'pxe' in name:
                self.assertIn('pxe', boot,
                              'boot interface should be based on pxe for %s' %
                              driver)
            if 'agent' in name:
                self.assertIn('direct', deploy,
                              'deploy interface should be direct for %s' %
                              driver)
            elif 'iscsi' in name or 'pxe' in name:
                self.assertIn('iscsi', deploy,
                              'deploy interface should be iscsi for %s' %
                              driver)
