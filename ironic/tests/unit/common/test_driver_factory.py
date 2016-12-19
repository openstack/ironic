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
from ironic.drivers import fake_hardware
from ironic.drivers import hardware_type
from ironic.drivers.modules import fake
from ironic.drivers.modules import noop
from ironic.tests import base
from ironic.tests.unit.db import base as db_base
from ironic.tests.unit.objects import utils as obj_utils


class FakeEp(object):
    name = 'fake'


class DriverLoadTestCase(base.TestCase):

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

    @mock.patch.object(driver_factory.LOG, 'warning', autospec=True)
    def test_driver_empty_entry(self, mock_log):
        self.config(enabled_drivers=['fake', ''])
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
    def test_get_driver_known(self):
        driver = driver_factory.get_driver('fake')
        self.assertIsInstance(driver, drivers_base.BaseDriver)

    def test_get_driver_unknown(self):
        self.assertRaises(exception.DriverNotFound,
                          driver_factory.get_driver, 'unknown_driver')


class NetworkInterfaceFactoryTestCase(db_base.DbTestCase):
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
        # NOTE(TheJulia) We should only check that the warn check is called,
        # as opposed to that the check is called a specific number of times,
        # during driver/interface loading in ironic. This is due to the fact
        # each activated interface or driver causes the number to increment.
        self.assertTrue(mock_warn.called)

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
        self.assertRaises(exception.InterfaceNotFoundInEntrypoint,
                          task_manager.acquire, self.context, node.id)


class StorageInterfaceFactoryTestCase(db_base.DbTestCase):

    def setUp(self):
        super(StorageInterfaceFactoryTestCase, self).setUp()
        driver_factory.DriverFactory._extension_manager = None
        driver_factory.StorageInterfaceFactory._extension_manager = None
        self.config(enabled_drivers=['fake'])

    def test_build_interface_for_task(self):
        """Validate a node has no default storage interface."""
        factory = driver_factory.StorageInterfaceFactory
        node = obj_utils.create_test_node(self.context, driver='fake')
        with task_manager.acquire(self.context, node.id) as task:
            manager = factory._extension_manager
            self.assertIn('noop', manager)
            self.assertEqual('noop', task.node.storage_interface)


class NewDriverFactory(driver_factory.BaseDriverFactory):
    _entrypoint_name = 'woof'


class NewFactoryTestCase(db_base.DbTestCase):
    def test_new_driver_factory_unknown_entrypoint(self):
        factory = NewDriverFactory()
        self.assertEqual('woof', factory._entrypoint_name)
        self.assertEqual([], factory._enabled_driver_list)


class CheckAndUpdateNodeInterfacesTestCase(db_base.DbTestCase):
    def test_no_network_interface(self):
        node = obj_utils.get_test_node(self.context, driver='fake')
        self.assertTrue(driver_factory.check_and_update_node_interfaces(node))
        self.assertEqual('flat', node.network_interface)

    def test_none_network_interface(self):
        node = obj_utils.get_test_node(self.context, driver='fake',
                                       network_interface=None)
        self.assertTrue(driver_factory.check_and_update_node_interfaces(node))
        self.assertEqual('flat', node.network_interface)

    def test_no_network_interface_default_from_conf(self):
        self.config(default_network_interface='noop')
        node = obj_utils.get_test_node(self.context, driver='fake')
        self.assertTrue(driver_factory.check_and_update_node_interfaces(node))
        self.assertEqual('noop', node.network_interface)

    def test_no_network_interface_default_from_dhcp(self):
        self.config(dhcp_provider='none', group='dhcp')
        node = obj_utils.get_test_node(self.context, driver='fake')
        self.assertTrue(driver_factory.check_and_update_node_interfaces(node))
        # "none" dhcp provider corresponds to "noop" network_interface
        self.assertEqual('noop', node.network_interface)

    def test_valid_interfaces(self):
        node = obj_utils.get_test_node(self.context, driver='fake',
                                       network_interface='noop',
                                       storage_interface='noop')
        self.assertFalse(driver_factory.check_and_update_node_interfaces(node))

    def test_invalid_network_interface(self):
        node = obj_utils.get_test_node(self.context, driver='fake',
                                       network_interface='banana')
        self.assertRaises(exception.InterfaceNotFoundInEntrypoint,
                          driver_factory.check_and_update_node_interfaces,
                          node)


class DefaultInterfaceTestCase(db_base.DbTestCase):
    def setUp(self):
        super(DefaultInterfaceTestCase, self).setUp()
        self.config(enabled_hardware_types=['manual-management'])
        self.driver = driver_factory.get_hardware_type('manual-management')

    def test_from_config(self):
        self.config(default_deploy_interface='direct')
        iface = driver_factory.default_interface(self.driver, 'deploy')
        self.assertEqual('direct', iface)

    def test_from_additional_defaults(self):
        self.config(default_storage_interface=None)
        iface = driver_factory.default_interface(self.driver, 'storage')
        self.assertEqual('noop', iface)

    def test_network_from_additional_defaults(self):
        self.config(default_network_interface=None)
        self.config(dhcp_provider='none', group='dhcp')
        iface = driver_factory.default_interface(self.driver, 'network')
        self.assertEqual('noop', iface)

    def test_network_from_additional_defaults_neutron_dhcp(self):
        self.config(default_network_interface=None)
        self.config(dhcp_provider='neutron', group='dhcp')
        iface = driver_factory.default_interface(self.driver, 'network')
        self.assertEqual('flat', iface)

    def test_calculated_with_one(self):
        self.config(default_deploy_interface=None)
        self.config(enabled_deploy_interfaces=['direct'])
        iface = driver_factory.default_interface(self.driver, 'deploy')
        self.assertEqual('direct', iface)

    def test_calculated_with_two(self):
        self.config(default_deploy_interface=None)
        self.config(enabled_deploy_interfaces=['iscsi', 'direct'])
        iface = driver_factory.default_interface(self.driver, 'deploy')
        self.assertEqual('iscsi', iface)

    def test_calculated_with_unsupported(self):
        self.config(default_deploy_interface=None)
        # manual-management doesn't support fake deploy
        self.config(enabled_deploy_interfaces=['fake', 'direct'])
        iface = driver_factory.default_interface(self.driver, 'deploy')
        self.assertEqual('direct', iface)

    def test_calculated_no_answer(self):
        # manual-management supports no power interfaces
        self.config(default_power_interface=None)
        self.config(enabled_power_interfaces=[])
        iface = driver_factory.default_interface(self.driver, 'power')
        self.assertIsNone(iface)


class TestFakeHardware(hardware_type.AbstractHardwareType):
    @property
    def supported_boot_interfaces(self):
        """List of supported boot interfaces."""
        return [fake.FakeBoot]

    @property
    def supported_console_interfaces(self):
        """List of supported console interfaces."""
        return [fake.FakeConsole]

    @property
    def supported_deploy_interfaces(self):
        """List of supported deploy interfaces."""
        return [fake.FakeDeploy]

    @property
    def supported_inspect_interfaces(self):
        """List of supported inspect interfaces."""
        return [fake.FakeInspect]

    @property
    def supported_management_interfaces(self):
        """List of supported management interfaces."""
        return [fake.FakeManagement]

    @property
    def supported_power_interfaces(self):
        """List of supported power interfaces."""
        return [fake.FakePower]

    @property
    def supported_raid_interfaces(self):
        """List of supported raid interfaces."""
        return [fake.FakeRAID]

    @property
    def supported_vendor_interfaces(self):
        """List of supported rescue interfaces."""
        return [fake.FakeVendorB, fake.FakeVendorA]


OPTIONAL_INTERFACES = set(drivers_base.BareDriver().standard_interfaces) - {
    'management', 'boot'}


class HardwareTypeLoadTestCase(db_base.DbTestCase):

    def setUp(self):
        super(HardwareTypeLoadTestCase, self).setUp()
        self.config(dhcp_provider=None, group='dhcp')
        self.ifaces = {}
        self.node_kwargs = {}
        for iface in drivers_base.ALL_INTERFACES:
            if iface == 'network':
                self.ifaces[iface] = 'noop'
                enabled = ['noop']
            elif iface == 'storage':
                self.ifaces[iface] = 'noop'
                enabled = ['noop']
            else:
                self.ifaces[iface] = 'fake'
                enabled = ['fake']
                if iface in OPTIONAL_INTERFACES:
                    enabled.append('no-%s' % iface)

            self.config(**{'enabled_%s_interfaces' % iface: enabled})
            self.node_kwargs['%s_interface' % iface] = self.ifaces[iface]

    def test_get_hardware_type_existing(self):
        hw_type = driver_factory.get_hardware_type('fake-hardware')
        self.assertIsInstance(hw_type, fake_hardware.FakeHardware)

    def test_get_hardware_type_missing(self):
        self.assertRaises(exception.DriverNotFound,
                          # "fake" is a classic driver
                          driver_factory.get_hardware_type, 'fake')

    def test_get_driver_or_hardware_type(self):
        hw_type = driver_factory.get_driver_or_hardware_type('fake-hardware')
        self.assertIsInstance(hw_type, fake_hardware.FakeHardware)
        driver = driver_factory.get_driver_or_hardware_type('fake')
        self.assertNotIsInstance(driver, fake_hardware.FakeHardware)

    def test_get_driver_or_hardware_type_missing(self):
        self.assertRaises(exception.DriverNotFound,
                          driver_factory.get_driver_or_hardware_type,
                          'banana')

    def test_build_driver_for_task(self):
        node = obj_utils.create_test_node(self.context, driver='fake-hardware',
                                          **self.node_kwargs)
        with task_manager.acquire(self.context, node.id) as task:
            for iface in drivers_base.ALL_INTERFACES:
                impl = getattr(task.driver, iface)
                self.assertIsNotNone(impl)

    def test_build_driver_for_task_incorrect(self):
        self.node_kwargs['power_interface'] = 'foobar'
        node = obj_utils.create_test_node(self.context, driver='fake-hardware',
                                          **self.node_kwargs)
        self.assertRaises(exception.InterfaceNotFoundInEntrypoint,
                          task_manager.acquire, self.context, node.id)

    def test_build_driver_for_task_fake(self):
        # Checks that fake driver is compatible with any interfaces, even those
        # which are not declared in supported_<INTERFACE>_interfaces result.
        self.node_kwargs['raid_interface'] = 'no-raid'
        node = obj_utils.create_test_node(self.context, driver='fake-hardware',
                                          **self.node_kwargs)
        with task_manager.acquire(self.context, node.id) as task:
            for iface in drivers_base.ALL_INTERFACES:
                impl = getattr(task.driver, iface)
                self.assertIsNotNone(impl)
            self.assertIsInstance(task.driver.raid, noop.NoRAID)

    @mock.patch.object(driver_factory, 'get_hardware_type', autospec=True,
                       return_value=TestFakeHardware())
    def test_build_driver_for_task_not_fake(self, mock_get_hw_type):
        # Checks that other hardware types do check compatibility.
        self.node_kwargs['raid_interface'] = 'no-raid'
        node = obj_utils.create_test_node(self.context, driver='fake-2',
                                          **self.node_kwargs)
        self.assertRaises(exception.IncompatibleInterface,
                          task_manager.acquire, self.context, node.id)
        mock_get_hw_type.assert_called_once_with('fake-2')

    def test_build_driver_for_task_no_defaults(self):
        self.config(dhcp_provider=None, group='dhcp')
        for iface in drivers_base.ALL_INTERFACES:
            if iface not in ['network', 'storage']:
                self.config(**{'enabled_%s_interfaces' % iface: []})
                self.config(**{'default_%s_interface' % iface: None})
        node = obj_utils.create_test_node(self.context, driver='fake-hardware')
        self.assertRaises(exception.NoValidDefaultForInterface,
                          task_manager.acquire, self.context, node.id)

    def test_build_driver_for_task_calculated_defaults(self):
        self.config(dhcp_provider=None, group='dhcp')
        node = obj_utils.create_test_node(self.context, driver='fake-hardware')
        with task_manager.acquire(self.context, node.id) as task:
            for iface in drivers_base.ALL_INTERFACES:
                impl = getattr(task.driver, iface)
                self.assertIsNotNone(impl)

    def test_build_driver_for_task_configured_defaults(self):
        for iface in drivers_base.ALL_INTERFACES:
            self.config(**{'default_%s_interface' % iface: self.ifaces[iface]})

        node = obj_utils.create_test_node(self.context, driver='fake-hardware')
        with task_manager.acquire(self.context, node.id) as task:
            for iface in drivers_base.ALL_INTERFACES:
                impl = getattr(task.driver, iface)
                self.assertIsNotNone(impl)
                self.assertEqual(self.ifaces[iface],
                                 getattr(task.node, '%s_interface' % iface))

    def test_build_driver_for_task_bad_default(self):
        self.config(default_power_interface='foobar')
        node = obj_utils.create_test_node(self.context, driver='fake-hardware')
        self.assertRaises(exception.InterfaceNotFoundInEntrypoint,
                          task_manager.acquire, self.context, node.id)

    def test_no_storage_interface(self):
        node = obj_utils.get_test_node(self.context, driver='fake')
        self.assertTrue(driver_factory.check_and_update_node_interfaces(node))
        self.assertEqual('noop', node.storage_interface)

    def test_none_storage_interface(self):
        node = obj_utils.get_test_node(self.context, driver='fake',
                                       storage_interface=None)
        self.assertTrue(driver_factory.check_and_update_node_interfaces(node))
        self.assertEqual('noop', node.storage_interface)

    def test_no_storage_interface_default_from_conf(self):
        self.config(enabled_storage_interfaces=['noop', 'fake'])
        self.config(default_storage_interface='fake')
        node = obj_utils.get_test_node(self.context, driver='fake')
        self.assertTrue(driver_factory.check_and_update_node_interfaces(node))
        self.assertEqual('fake', node.storage_interface)

    def test_invalid_storage_interface(self):
        node = obj_utils.get_test_node(self.context, driver='fake',
                                       storage_interface='scoop')
        self.assertRaises(exception.InterfaceNotFoundInEntrypoint,
                          driver_factory.check_and_update_node_interfaces,
                          node)

    def _test_enabled_supported_interfaces(self, enable_storage):
        ht = fake_hardware.FakeHardware()
        expected = {
            'boot': set(['fake']),
            'console': set(['fake']),
            'deploy': set(['fake']),
            'inspect': set(['fake']),
            'management': set(['fake']),
            'network': set(['noop']),
            'power': set(['fake']),
            'raid': set(['fake']),
            'storage': set([]),
            'vendor': set(['fake'])
        }
        if enable_storage:
            self.config(enabled_storage_interfaces=['fake'])
            expected['storage'] = set(['fake'])

        mapping = driver_factory.enabled_supported_interfaces(ht)
        self.assertEqual(expected, mapping)

    def test_enabled_supported_interfaces(self):
        self._test_enabled_supported_interfaces(False)

    def test_enabled_supported_interfaces_non_default(self):
        self._test_enabled_supported_interfaces(True)
