# Copyright 2014 Hewlett-Packard Development Company, L.P.
#
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


"""Test class for Management Interface used by iLO modules."""

from unittest import mock

from ironic.common import exception
from ironic.common import states
from ironic.common import utils
from ironic.conductor import task_manager
from ironic.conductor import utils as conductor_utils
from ironic.drivers.modules.ilo import common as ilo_common
from ironic.drivers.modules.ilo import inspect as ilo_inspect
from ironic.drivers.modules.ilo import power as ilo_power
from ironic.drivers.modules import inspect_utils
from ironic.tests.unit.drivers.modules.ilo import test_common


class IloInspectTestCase(test_common.BaseIloTest):

    def test_get_properties(self):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            properties = ilo_common.REQUIRED_PROPERTIES.copy()
            properties.update(ilo_common.SNMP_PROPERTIES)
            properties.update(ilo_common.SNMP_OPTIONAL_PROPERTIES)
            self.assertEqual(properties,
                             task.driver.inspect.get_properties())

    @mock.patch.object(ilo_common, 'parse_driver_info', spec_set=True,
                       autospec=True)
    def test_validate(self, driver_info_mock):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.driver.inspect.validate(task)
            driver_info_mock.assert_called_once_with(task.node)

    @mock.patch.object(ilo_inspect, '_get_capabilities', spec_set=True,
                       autospec=True)
    @mock.patch.object(inspect_utils, 'create_ports_if_not_exist',
                       spec_set=True, autospec=True)
    @mock.patch.object(ilo_inspect, '_get_essential_properties', spec_set=True,
                       autospec=True)
    @mock.patch.object(ilo_power.IloPower, 'get_power_state', spec_set=True,
                       autospec=True)
    @mock.patch.object(ilo_common, 'get_ilo_object', spec_set=True,
                       autospec=True)
    def test_inspect_essential_ok(self, get_ilo_object_mock,
                                  power_mock,
                                  get_essential_mock,
                                  create_port_mock,
                                  get_capabilities_mock):
        ilo_object_mock = get_ilo_object_mock.return_value
        properties = {'memory_mb': '512', 'local_gb': '10',
                      'cpus': '1', 'cpu_arch': 'x86_64'}
        macs = {'Port 1': 'aa:aa:aa:aa:aa:aa', 'Port 2': 'bb:bb:bb:bb:bb:bb'}
        capabilities = {}
        result = {'properties': properties, 'macs': macs}
        get_essential_mock.return_value = result
        get_capabilities_mock.return_value = capabilities
        power_mock.return_value = states.POWER_ON
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.driver.inspect.inspect_hardware(task)
            self.assertEqual(properties, task.node.properties)
            power_mock.assert_called_once_with(mock.ANY, task)
            get_essential_mock.assert_called_once_with(task.node,
                                                       ilo_object_mock)
            get_capabilities_mock.assert_called_once_with(task.node,
                                                          ilo_object_mock)
            create_port_mock.assert_called_once_with(task, macs)

    @mock.patch.object(ilo_inspect.LOG, 'warning',
                       spec_set=True, autospec=True)
    @mock.patch.object(ilo_inspect, '_get_capabilities', spec_set=True,
                       autospec=True)
    @mock.patch.object(inspect_utils, 'create_ports_if_not_exist',
                       spec_set=True, autospec=True)
    @mock.patch.object(ilo_inspect, '_get_essential_properties', spec_set=True,
                       autospec=True)
    @mock.patch.object(ilo_power.IloPower, 'get_power_state', spec_set=True,
                       autospec=True)
    @mock.patch.object(ilo_common, 'get_ilo_object', spec_set=True,
                       autospec=True)
    def test_inspect_essential_ok_local_gb_zero(self, get_ilo_object_mock,
                                                power_mock,
                                                get_essential_mock,
                                                create_port_mock,
                                                get_capabilities_mock,
                                                log_mock):
        ilo_object_mock = get_ilo_object_mock.return_value
        properties = {'memory_mb': '512', 'local_gb': 0,
                      'cpus': '1', 'cpu_arch': 'x86_64'}
        macs = {'Port 1': 'aa:aa:aa:aa:aa:aa', 'Port 2': 'bb:bb:bb:bb:bb:bb'}
        capabilities = {}
        result = {'properties': properties, 'macs': macs}
        get_essential_mock.return_value = result
        get_capabilities_mock.return_value = capabilities
        power_mock.return_value = states.POWER_ON
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            properties = task.node.properties
            properties['local_gb'] = 10
            task.node.properties = properties
            task.node.save()
            expected_properties = {'memory_mb': '512', 'local_gb': 10,
                                   'cpus': '1', 'cpu_arch': 'x86_64'}
            task.driver.inspect.inspect_hardware(task)
            self.assertEqual(expected_properties, task.node.properties)
            power_mock.assert_called_once_with(mock.ANY, task)
            get_essential_mock.assert_called_once_with(task.node,
                                                       ilo_object_mock)
            self.assertTrue(log_mock.called)
            get_capabilities_mock.assert_called_once_with(task.node,
                                                          ilo_object_mock)
            create_port_mock.assert_called_once_with(task, macs)

    @mock.patch.object(ilo_inspect.LOG, 'warning',
                       spec_set=True, autospec=True)
    @mock.patch.object(ilo_inspect, '_get_capabilities', spec_set=True,
                       autospec=True)
    @mock.patch.object(inspect_utils, 'create_ports_if_not_exist',
                       spec_set=True, autospec=True)
    @mock.patch.object(ilo_inspect, '_get_essential_properties', spec_set=True,
                       autospec=True)
    @mock.patch.object(ilo_power.IloPower, 'get_power_state', spec_set=True,
                       autospec=True)
    @mock.patch.object(ilo_common, 'get_ilo_object', spec_set=True,
                       autospec=True)
    def test_inspect_ok_gen8(self, get_ilo_object_mock,
                             power_mock,
                             get_essential_mock,
                             create_port_mock,
                             get_capabilities_mock,
                             log_mock):
        ilo_object_mock = get_ilo_object_mock.return_value
        properties = {'memory_mb': '512', 'local_gb': 10,
                      'cpus': '1', 'cpu_arch': 'x86_64'}
        macs = {'Port 1': 'aa:aa:aa:aa:aa:aa', 'Port 2': 'bb:bb:bb:bb:bb:bb'}
        capabilities = {'server_model': 'Gen8'}
        result = {'properties': properties, 'macs': macs}
        get_essential_mock.return_value = result
        get_capabilities_mock.return_value = capabilities
        power_mock.return_value = states.POWER_ON
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            expected_properties = {'memory_mb': '512', 'local_gb': 10,
                                   'cpus': '1', 'cpu_arch': 'x86_64',
                                   'capabilities': 'server_model:Gen8'}
            task.driver.inspect.inspect_hardware(task)
            self.assertEqual(expected_properties, task.node.properties)
            power_mock.assert_called_once_with(mock.ANY, task)
            get_essential_mock.assert_called_once_with(task.node,
                                                       ilo_object_mock)
            self.assertTrue(log_mock.called)
            get_capabilities_mock.assert_called_once_with(task.node,
                                                          ilo_object_mock)
            create_port_mock.assert_called_once_with(task, macs)

    @mock.patch.object(ilo_inspect.LOG, 'warning',
                       spec_set=True, autospec=True)
    @mock.patch.object(ilo_inspect, '_get_capabilities', spec_set=True,
                       autospec=True)
    @mock.patch.object(inspect_utils, 'create_ports_if_not_exist',
                       spec_set=True, autospec=True)
    @mock.patch.object(ilo_inspect, '_get_essential_properties', spec_set=True,
                       autospec=True)
    @mock.patch.object(ilo_power.IloPower, 'get_power_state', spec_set=True,
                       autospec=True)
    @mock.patch.object(ilo_common, 'get_ilo_object', spec_set=True,
                       autospec=True)
    def test_inspect_ok_gen10(self, get_ilo_object_mock,
                              power_mock,
                              get_essential_mock,
                              create_port_mock,
                              get_capabilities_mock,
                              log_mock):
        ilo_object_mock = get_ilo_object_mock.return_value
        properties = {'memory_mb': '512', 'local_gb': 10,
                      'cpus': '1', 'cpu_arch': 'x86_64'}
        macs = {'NIC.LOM.1.1': 'aa:aa:aa:aa:aa:aa'}
        capabilities = {'server_model': 'Gen10'}
        result = {'properties': properties, 'macs': macs}
        get_essential_mock.return_value = result
        get_capabilities_mock.return_value = capabilities
        power_mock.return_value = states.POWER_ON
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            expected_properties = {'memory_mb': '512', 'local_gb': 10,
                                   'cpus': '1', 'cpu_arch': 'x86_64',
                                   'capabilities': 'server_model:Gen10'}
            task.driver.inspect.inspect_hardware(task)
            self.assertEqual(expected_properties, task.node.properties)
            power_mock.assert_called_once_with(mock.ANY, task)
            get_essential_mock.assert_called_once_with(task.node,
                                                       ilo_object_mock)
            self.assertFalse(log_mock.called)
            get_capabilities_mock.assert_called_once_with(task.node,
                                                          ilo_object_mock)
            create_port_mock.assert_called_once_with(task, macs)

    @mock.patch.object(ilo_inspect, '_get_capabilities', spec_set=True,
                       autospec=True)
    @mock.patch.object(inspect_utils, 'create_ports_if_not_exist',
                       spec_set=True, autospec=True)
    @mock.patch.object(ilo_inspect, '_get_essential_properties', spec_set=True,
                       autospec=True)
    @mock.patch.object(conductor_utils, 'node_power_action', spec_set=True,
                       autospec=True)
    @mock.patch.object(ilo_power.IloPower, 'get_power_state', spec_set=True,
                       autospec=True)
    @mock.patch.object(ilo_common, 'get_ilo_object', spec_set=True,
                       autospec=True)
    def test_inspect_essential_ok_power_off(self, get_ilo_object_mock,
                                            power_mock,
                                            set_power_mock,
                                            get_essential_mock,
                                            create_port_mock,
                                            get_capabilities_mock):
        ilo_object_mock = get_ilo_object_mock.return_value
        properties = {'memory_mb': '512', 'local_gb': '10',
                      'cpus': '1', 'cpu_arch': 'x86_64'}
        macs = {'Port 1': 'aa:aa:aa:aa:aa:aa', 'Port 2': 'bb:bb:bb:bb:bb:bb'}
        capabilities = {}
        result = {'properties': properties, 'macs': macs}
        get_essential_mock.return_value = result
        get_capabilities_mock.return_value = capabilities
        power_mock.return_value = states.POWER_OFF
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.driver.inspect.inspect_hardware(task)
            self.assertEqual(properties, task.node.properties)
            power_mock.assert_called_once_with(mock.ANY, task)
            set_power_mock.assert_any_call(task, states.POWER_ON)
            get_essential_mock.assert_called_once_with(task.node,
                                                       ilo_object_mock)
            get_capabilities_mock.assert_called_once_with(task.node,
                                                          ilo_object_mock)
            create_port_mock.assert_called_once_with(task, macs)

    @mock.patch.object(ilo_inspect, '_get_capabilities', spec_set=True,
                       autospec=True)
    @mock.patch.object(inspect_utils, 'create_ports_if_not_exist',
                       spec_set=True, autospec=True)
    @mock.patch.object(ilo_inspect, '_get_essential_properties', spec_set=True,
                       autospec=True)
    @mock.patch.object(ilo_power.IloPower, 'get_power_state', spec_set=True,
                       autospec=True)
    @mock.patch.object(ilo_common, 'get_ilo_object', spec_set=True,
                       autospec=True)
    def test_inspect_essential_capabilities_ok(self, get_ilo_object_mock,
                                               power_mock,
                                               get_essential_mock,
                                               create_port_mock,
                                               get_capabilities_mock):
        ilo_object_mock = get_ilo_object_mock.return_value
        properties = {'memory_mb': '512', 'local_gb': '10',
                      'cpus': '1', 'cpu_arch': 'x86_64'}
        macs = {'Port 1': 'aa:aa:aa:aa:aa:aa', 'Port 2': 'bb:bb:bb:bb:bb:bb'}
        capability_str = 'sriov_enabled:true'
        capabilities = {'sriov_enabled': 'true'}
        result = {'properties': properties, 'macs': macs}
        get_essential_mock.return_value = result
        get_capabilities_mock.return_value = capabilities
        power_mock.return_value = states.POWER_ON
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.driver.inspect.inspect_hardware(task)
            expected_properties = {'memory_mb': '512', 'local_gb': '10',
                                   'cpus': '1', 'cpu_arch': 'x86_64',
                                   'capabilities': capability_str}
            self.assertEqual(expected_properties, task.node.properties)
            power_mock.assert_called_once_with(mock.ANY, task)
            get_essential_mock.assert_called_once_with(task.node,
                                                       ilo_object_mock)
            get_capabilities_mock.assert_called_once_with(task.node,
                                                          ilo_object_mock)
            create_port_mock.assert_called_once_with(task, macs)

    @mock.patch.object(ilo_inspect, '_get_capabilities', spec_set=True,
                       autospec=True)
    @mock.patch.object(inspect_utils, 'create_ports_if_not_exist',
                       spec_set=True, autospec=True)
    @mock.patch.object(ilo_inspect, '_get_essential_properties', spec_set=True,
                       autospec=True)
    @mock.patch.object(ilo_power.IloPower, 'get_power_state', spec_set=True,
                       autospec=True)
    @mock.patch.object(ilo_common, 'get_ilo_object', spec_set=True,
                       autospec=True)
    def test_inspect_essential_capabilities_exist_ok(self, get_ilo_object_mock,
                                                     power_mock,
                                                     get_essential_mock,
                                                     create_port_mock,
                                                     get_capabilities_mock):
        ilo_object_mock = get_ilo_object_mock.return_value
        properties = {'memory_mb': '512', 'local_gb': '10',
                      'cpus': '1', 'cpu_arch': 'x86_64',
                      'somekey': 'somevalue'}
        macs = {'Port 1': 'aa:aa:aa:aa:aa:aa', 'Port 2': 'bb:bb:bb:bb:bb:bb'}
        result = {'properties': properties, 'macs': macs}
        capabilities = {'sriov_enabled': 'true'}
        get_essential_mock.return_value = result
        get_capabilities_mock.return_value = capabilities
        power_mock.return_value = states.POWER_ON
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.node.properties = {'capabilities': 'boot_mode:uefi'}
            expected_capabilities = ('sriov_enabled:true,'
                                     'boot_mode:uefi')
            set1 = set(expected_capabilities.split(','))
            task.driver.inspect.inspect_hardware(task)
            end_capabilities = task.node.properties['capabilities']
            set2 = set(end_capabilities.split(','))
            self.assertEqual(set1, set2)
            expected_properties = {'memory_mb': '512', 'local_gb': '10',
                                   'cpus': '1', 'cpu_arch': 'x86_64',
                                   'capabilities': end_capabilities}
            power_mock.assert_called_once_with(mock.ANY, task)
            self.assertEqual(task.node.properties, expected_properties)
            get_essential_mock.assert_called_once_with(task.node,
                                                       ilo_object_mock)
            get_capabilities_mock.assert_called_once_with(task.node,
                                                          ilo_object_mock)
            create_port_mock.assert_called_once_with(task, macs)


class TestInspectPrivateMethods(test_common.BaseIloTest):

    def test__get_essential_properties_ok(self):
        ilo_mock = mock.MagicMock(spec=['get_essential_properties'])
        properties = {'memory_mb': '512', 'local_gb': '10',
                      'cpus': '1', 'cpu_arch': 'x86_64'}
        macs = {'Port 1': 'aa:aa:aa:aa:aa:aa', 'Port 2': 'bb:bb:bb:bb:bb:bb'}
        result = {'properties': properties, 'macs': macs}
        ilo_mock.get_essential_properties.return_value = result
        actual_result = ilo_inspect._get_essential_properties(self.node,
                                                              ilo_mock)
        self.assertEqual(result, actual_result)

    def test__get_essential_properties_fail(self):
        ilo_mock = mock.MagicMock(
            spec=['get_additional_capabilities', 'get_essential_properties'])
        # Missing key: cpu_arch
        properties = {'memory_mb': '512', 'local_gb': '10',
                      'cpus': '1'}
        macs = {'Port 1': 'aa:aa:aa:aa:aa:aa', 'Port 2': 'bb:bb:bb:bb:bb:bb'}
        result = {'properties': properties, 'macs': macs}
        ilo_mock.get_essential_properties.return_value = result
        result = self.assertRaises(exception.HardwareInspectionFailure,
                                   ilo_inspect._get_essential_properties,
                                   self.node,
                                   ilo_mock)
        self.assertEqual(
            str(result),
            ("Failed to inspect hardware. Reason: Server didn't return the "
             "key(s): cpu_arch"))

    def test__get_essential_properties_fail_invalid_format(self):
        ilo_mock = mock.MagicMock(
            spec=['get_additional_capabilities', 'get_essential_properties'])
        # Not a dict
        properties = ['memory_mb', '512', 'local_gb', '10',
                      'cpus', '1']
        macs = ['aa:aa:aa:aa:aa:aa', 'bb:bb:bb:bb:bb:bb']
        capabilities = ''
        result = {'properties': properties, 'macs': macs}
        ilo_mock.get_essential_properties.return_value = result
        ilo_mock.get_additional_capabilities.return_value = capabilities
        self.assertRaises(exception.HardwareInspectionFailure,
                          ilo_inspect._get_essential_properties,
                          self.node, ilo_mock)

    def test__get_essential_properties_fail_mac_invalid_format(self):
        ilo_mock = mock.MagicMock(spec=['get_essential_properties'])
        properties = {'memory_mb': '512', 'local_gb': '10',
                      'cpus': '1', 'cpu_arch': 'x86_64'}
        # Not a dict
        macs = 'aa:aa:aa:aa:aa:aa'
        result = {'properties': properties, 'macs': macs}
        ilo_mock.get_essential_properties.return_value = result
        self.assertRaises(exception.HardwareInspectionFailure,
                          ilo_inspect._get_essential_properties,
                          self.node, ilo_mock)

    def test__get_essential_properties_hardware_port_empty(self):
        ilo_mock = mock.MagicMock(
            spec=['get_additional_capabilities', 'get_essential_properties'])
        properties = {'memory_mb': '512', 'local_gb': '10',
                      'cpus': '1', 'cpu_arch': 'x86_64'}
        # Not a dictionary
        macs = None
        result = {'properties': properties, 'macs': macs}
        capabilities = ''
        ilo_mock.get_essential_properties.return_value = result
        ilo_mock.get_additional_capabilities.return_value = capabilities
        self.assertRaises(exception.HardwareInspectionFailure,
                          ilo_inspect._get_essential_properties,
                          self.node, ilo_mock)

    def test__get_essential_properties_hardware_port_not_dict(self):
        ilo_mock = mock.MagicMock(spec=['get_essential_properties'])
        properties = {'memory_mb': '512', 'local_gb': '10',
                      'cpus': '1', 'cpu_arch': 'x86_64'}
        # Not a dict
        macs = 'aa:bb:cc:dd:ee:ff'
        result = {'properties': properties, 'macs': macs}
        ilo_mock.get_essential_properties.return_value = result
        result = self.assertRaises(
            exception.HardwareInspectionFailure,
            ilo_inspect._get_essential_properties, self.node, ilo_mock)

    @mock.patch.object(utils, 'get_updated_capabilities', spec_set=True,
                       autospec=True)
    def test__get_capabilities_ok(self, capability_mock):
        ilo_mock = mock.MagicMock(spec=['get_server_capabilities'])
        capabilities = {'ilo_firmware_version': 'xyz'}
        ilo_mock.get_server_capabilities.return_value = capabilities
        cap = ilo_inspect._get_capabilities(self.node, ilo_mock)
        self.assertEqual(cap, capabilities)

    def test__validate_ok(self):
        properties = {'memory_mb': '512', 'local_gb': '10',
                      'cpus': '2', 'cpu_arch': 'x86_arch'}
        macs = {'Port 1': 'aa:aa:aa:aa:aa:aa'}
        data = {'properties': properties, 'macs': macs}
        valid_keys = ilo_inspect.IloInspect.ESSENTIAL_PROPERTIES
        ilo_inspect._validate(self.node, data)
        self.assertEqual(sorted(set(properties)), sorted(valid_keys))

    def test__validate_essential_keys_fail_missing_key(self):
        properties = {'memory_mb': '512', 'local_gb': '10',
                      'cpus': '1'}
        macs = {'Port 1': 'aa:aa:aa:aa:aa:aa'}
        data = {'properties': properties, 'macs': macs}
        self.assertRaises(exception.HardwareInspectionFailure,
                          ilo_inspect._validate, self.node, data)

    def test___create_supported_capabilities_dict(self):
        capabilities = {}
        expected = {}
        for key in ilo_inspect.CAPABILITIES_KEYS:
            capabilities.update({key: 'true'})
            expected.update({key: 'true'})
        capabilities.update({'unknown_property': 'true'})
        cap = ilo_inspect._create_supported_capabilities_dict(capabilities)
        self.assertEqual(expected, cap)

    def test___create_supported_capabilities_dict_excluded_capability(self):
        capabilities = {}
        expected = {}
        for key in ilo_inspect.CAPABILITIES_KEYS - {'has_ssd'}:
            capabilities.update({key: 'true'})
            expected.update({key: 'true'})
        cap = ilo_inspect._create_supported_capabilities_dict(capabilities)
        self.assertEqual(expected, cap)
