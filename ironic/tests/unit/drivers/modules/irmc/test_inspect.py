# Copyright 2015 FUJITSU LIMITED
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

"""
Test class for iRMC Inspection Driver
"""

import mock

from ironic.common import exception
from ironic.common import states
from ironic.common import utils
from ironic.conductor import task_manager
from ironic.conductor import utils as manager_utils
from ironic.drivers.modules.irmc import common as irmc_common
from ironic.drivers.modules.irmc import inspect as irmc_inspect
from ironic.drivers.modules.irmc import power as irmc_power
from ironic import objects
from ironic.tests.unit.drivers import (
    third_party_driver_mock_specs as mock_specs
)
from ironic.tests.unit.drivers.modules.irmc import test_common


class IRMCInspectInternalMethodsTestCase(test_common.BaseIRMCTest):

    @mock.patch('ironic.drivers.modules.irmc.inspect.snmp.SNMPClient',
                spec_set=True, autospec=True)
    def test__get_mac_addresses(self, snmpclient_mock):
        snmpclient_mock.return_value = mock.Mock(
            **{'get_next.side_effect': [[2, 2, 7],
                                        ['\xaa\xaa\xaa\xaa\xaa\xaa',
                                         '\xbb\xbb\xbb\xbb\xbb\xbb',
                                         '\xcc\xcc\xcc\xcc\xcc\xcc']]})
        inspected_macs = ['aa:aa:aa:aa:aa:aa', 'bb:bb:bb:bb:bb:bb']
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            result = irmc_inspect._get_mac_addresses(task.node)
            self.assertEqual(inspected_macs, result)

    @mock.patch.object(irmc_inspect, '_get_mac_addresses', spec_set=True,
                       autospec=True)
    @mock.patch.object(irmc_inspect, 'scci',
                       spec_set=mock_specs.SCCICLIENT_IRMC_SCCI_SPEC)
    @mock.patch.object(irmc_common, 'get_irmc_report', spec_set=True,
                       autospec=True)
    def test__inspect_hardware(
            self, get_irmc_report_mock, scci_mock, _get_mac_addresses_mock):
        # Set config flags
        gpu_ids = ['0x1000/0x0079', '0x2100/0x0080']
        cpu_fpgas = ['0x1000/0x0179', '0x2100/0x0180']
        self.config(gpu_ids=gpu_ids, group='irmc')
        self.config(fpga_ids=cpu_fpgas, group='irmc')
        kwargs = {'sleep_flag': False}

        inspected_props = {
            'memory_mb': '1024',
            'local_gb': 10,
            'cpus': 2,
            'cpu_arch': 'x86_64'}
        inspected_capabilities = {
            'trusted_boot': False,
            'irmc_firmware_version': 'iRMC S4-7.82F',
            'server_model': 'TX2540M1F5',
            'rom_firmware_version': 'V4.6.5.4 R1.15.0 for D3099-B1x',
            'pci_gpu_devices': 1,
            'cpu_fpga': 1}
        new_traits = ['CUSTOM_CPU_FPGA']
        existing_traits = []

        inspected_macs = ['aa:aa:aa:aa:aa:aa', 'bb:bb:bb:bb:bb:bb']
        report = 'fake_report'
        get_irmc_report_mock.return_value = report
        scci_mock.get_essential_properties.return_value = inspected_props
        scci_mock.get_capabilities_properties.return_value = (
            inspected_capabilities)
        _get_mac_addresses_mock.return_value = inspected_macs
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            result = irmc_inspect._inspect_hardware(task.node,
                                                    existing_traits,
                                                    **kwargs)
            get_irmc_report_mock.assert_called_once_with(task.node)
            scci_mock.get_essential_properties.assert_called_once_with(
                report, irmc_inspect.IRMCInspect.ESSENTIAL_PROPERTIES)
            scci_mock.get_capabilities_properties.assert_called_once_with(
                mock.ANY, irmc_inspect.CAPABILITIES_PROPERTIES,
                gpu_ids, fpga_ids=cpu_fpgas, **kwargs)

            expected_props = dict(inspected_props)
            inspected_capabilities = utils.get_updated_capabilities(
                '', inspected_capabilities)
            expected_props['capabilities'] = inspected_capabilities
            self.assertEqual((expected_props, inspected_macs, new_traits),
                             result)

    @mock.patch.object(irmc_inspect, '_get_mac_addresses', spec_set=True,
                       autospec=True)
    @mock.patch.object(irmc_inspect, 'scci',
                       spec_set=mock_specs.SCCICLIENT_IRMC_SCCI_SPEC)
    @mock.patch.object(irmc_common, 'get_irmc_report', spec_set=True,
                       autospec=True)
    def test__inspect_hardware_exception(
            self, get_irmc_report_mock, scci_mock, _get_mac_addresses_mock):
        report = 'fake_report'
        kwargs = {'sleep_flag': False}
        get_irmc_report_mock.return_value = report
        side_effect = exception.SNMPFailure("fake exception")
        scci_mock.get_essential_properties.side_effect = side_effect
        irmc_inspect.scci.SCCIInvalidInputError = Exception
        irmc_inspect.scci.SCCIClientError = Exception

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            self.assertRaises(exception.HardwareInspectionFailure,
                              irmc_inspect._inspect_hardware,
                              task.node, **kwargs)
            get_irmc_report_mock.assert_called_once_with(task.node)
            self.assertFalse(_get_mac_addresses_mock.called)


class IRMCInspectTestCase(test_common.BaseIRMCTest):

    def test_get_properties(self):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            properties = task.driver.get_properties()
            for prop in irmc_common.COMMON_PROPERTIES:
                self.assertIn(prop, properties)

    @mock.patch.object(irmc_common, 'parse_driver_info', spec_set=True,
                       autospec=True)
    def test_validate(self, parse_driver_info_mock):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            task.driver.inspect.validate(task)
            parse_driver_info_mock.assert_called_once_with(task.node)

    @mock.patch.object(irmc_common, 'parse_driver_info', spec_set=True,
                       autospec=True)
    def test_validate_fail(self, parse_driver_info_mock):
        side_effect = exception.InvalidParameterValue("Invalid Input")
        parse_driver_info_mock.side_effect = side_effect

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            self.assertRaises(exception.InvalidParameterValue,
                              task.driver.inspect.validate,
                              task)

    def test__init_fail_invalid_gpu_ids_input(self):
        # Set config flags
        self.config(gpu_ids='100/x079,0x20/', group='irmc')
        self.assertRaises(exception.InvalidParameterValue,
                          irmc_inspect.IRMCInspect)

    def test__init_fail_invalid_fpga_ids_input(self):
        # Set config flags
        self.config(fpga_ids='100/x079,0x20/', group='irmc')
        self.assertRaises(exception.InvalidParameterValue,
                          irmc_inspect.IRMCInspect)

    @mock.patch.object(irmc_inspect.LOG, 'info', spec_set=True, autospec=True)
    @mock.patch('ironic.drivers.modules.irmc.inspect.objects.Port',
                spec_set=True, autospec=True)
    @mock.patch.object(irmc_inspect, '_inspect_hardware', spec_set=True,
                       autospec=True)
    @mock.patch.object(irmc_power.IRMCPower, 'get_power_state', spec_set=True,
                       autospec=True)
    def test_inspect_hardware(self, power_state_mock, _inspect_hardware_mock,
                              port_mock, info_mock):
        inspected_props = {
            'memory_mb': '1024',
            'local_gb': 10,
            'cpus': 2,
            'cpu_arch': 'x86_64'}
        inspected_macs = ['aa:aa:aa:aa:aa:aa', 'bb:bb:bb:bb:bb:bb']
        new_traits = ['CUSTOM_CPU_FPGA']
        existing_traits = []
        power_state_mock.return_value = states.POWER_ON
        _inspect_hardware_mock.return_value = (inspected_props,
                                               inspected_macs,
                                               new_traits)
        new_port_mock1 = mock.MagicMock(spec=objects.Port)
        new_port_mock2 = mock.MagicMock(spec=objects.Port)

        port_mock.side_effect = [new_port_mock1, new_port_mock2]

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            result = task.driver.inspect.inspect_hardware(task)

            node_id = task.node.id
            _inspect_hardware_mock.assert_called_once_with(task.node,
                                                           existing_traits)

            # note (naohirot):
            # as of mock 1.2, assert_has_calls has a bug which returns
            # "AssertionError: Calls not found." if mock_calls has class
            # method call such as below:

            # AssertionError: Calls not found.
            # Expected: [call.list_by_node_id(
            #  <oslo_context.context.RequestContext object at 0x7f1a34f8c0d0>,
            #  1)]
            # Actual: [call.list_by_node_id(
            #  <oslo_context.context.RequestContext object at 0x7f1a34f8c0d0>,
            #  1)]
            #
            # workaround, remove class method call from mock_calls list
            del port_mock.mock_calls[0]
            port_mock.assert_has_calls([
                # workaround, comment out class method call from expected list
                # mock.call.list_by_node_id(task.context, node_id),
                mock.call(task.context, address=inspected_macs[0],
                          node_id=node_id),
                mock.call(task.context, address=inspected_macs[1],
                          node_id=node_id)
            ])
            new_port_mock1.create.assert_called_once_with()
            new_port_mock2.create.assert_called_once_with()

            self.assertTrue(info_mock.called)
            task.node.refresh()
            self.assertEqual(inspected_props, task.node.properties)
            self.assertEqual(states.MANAGEABLE, result)

    @mock.patch.object(manager_utils, 'node_power_action', spec_set=True,
                       autospec=True)
    @mock.patch.object(manager_utils, 'node_set_boot_device', spec_set=True,
                       autospec=True)
    @mock.patch.object(irmc_inspect.LOG, 'info', spec_set=True, autospec=True)
    @mock.patch.object(irmc_inspect.objects, 'Port',
                       spec_set=True, autospec=True)
    @mock.patch.object(irmc_inspect, '_inspect_hardware', spec_set=True,
                       autospec=True)
    @mock.patch.object(irmc_power.IRMCPower, 'get_power_state', spec_set=True,
                       autospec=True)
    def test_inspect_hardware_with_power_off(self, power_state_mock,
                                             _inspect_hardware_mock,
                                             port_mock, info_mock,
                                             set_boot_device_mock,
                                             power_action_mock):
        inspected_props = {
            'memory_mb': '1024',
            'local_gb': 10,
            'cpus': 2,
            'cpu_arch': 'x86_64'}
        inspected_macs = ['aa:aa:aa:aa:aa:aa', 'bb:bb:bb:bb:bb:bb']
        new_traits = ['CUSTOM_CPU_FPGA']
        existing_traits = []
        power_state_mock.return_value = states.POWER_OFF
        _inspect_hardware_mock.return_value = (inspected_props,
                                               inspected_macs,
                                               new_traits)
        new_port_mock1 = mock.MagicMock(spec=objects.Port)
        new_port_mock2 = mock.MagicMock(spec=objects.Port)

        port_mock.side_effect = [new_port_mock1, new_port_mock2]

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            result = task.driver.inspect.inspect_hardware(task)

            node_id = task.node.id
            _inspect_hardware_mock.assert_called_once_with(task.node,
                                                           existing_traits,
                                                           sleep_flag=True)

            port_mock.assert_has_calls([
                mock.call(task.context, address=inspected_macs[0],
                          node_id=node_id),
                mock.call(task.context, address=inspected_macs[1],
                          node_id=node_id)
            ])
            new_port_mock1.create.assert_called_once_with()
            new_port_mock2.create.assert_called_once_with()

            self.assertTrue(info_mock.called)
            task.node.refresh()
            self.assertEqual(inspected_props, task.node.properties)
            self.assertEqual(states.MANAGEABLE, result)
            self.assertEqual(power_action_mock.called, True)
            self.assertEqual(power_action_mock.call_count, 2)

    @mock.patch('ironic.objects.Port', spec_set=True, autospec=True)
    @mock.patch.object(irmc_inspect, '_inspect_hardware', spec_set=True,
                       autospec=True)
    @mock.patch.object(irmc_power.IRMCPower, 'get_power_state', spec_set=True,
                       autospec=True)
    def test_inspect_hardware_inspect_exception(
            self, power_state_mock, _inspect_hardware_mock, port_mock):
        side_effect = exception.HardwareInspectionFailure("fake exception")
        _inspect_hardware_mock.side_effect = side_effect
        power_state_mock.return_value = states.POWER_ON

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            self.assertRaises(exception.HardwareInspectionFailure,
                              task.driver.inspect.inspect_hardware,
                              task)
            self.assertFalse(port_mock.called)

    @mock.patch.object(objects.trait.TraitList,
                       'get_trait_names',
                       spec_set=True,
                       autospec=True)
    @mock.patch.object(irmc_inspect.LOG, 'warn', spec_set=True, autospec=True)
    @mock.patch('ironic.objects.Port', spec_set=True, autospec=True)
    @mock.patch.object(irmc_inspect, '_inspect_hardware', spec_set=True,
                       autospec=True)
    @mock.patch.object(irmc_power.IRMCPower, 'get_power_state', spec_set=True,
                       autospec=True)
    def test_inspect_hardware_mac_already_exist(
            self, power_state_mock, _inspect_hardware_mock,
            port_mock, warn_mock, trait_mock):
        inspected_props = {
            'memory_mb': '1024',
            'local_gb': 10,
            'cpus': 2,
            'cpu_arch': 'x86_64'}
        inspected_macs = ['aa:aa:aa:aa:aa:aa', 'bb:bb:bb:bb:bb:bb']
        existing_traits = ['CUSTOM_CPU_FPGA']
        new_traits = list(existing_traits)
        _inspect_hardware_mock.return_value = (inspected_props,
                                               inspected_macs,
                                               new_traits)
        power_state_mock.return_value = states.POWER_ON
        side_effect = exception.MACAlreadyExists("fake exception")
        new_port_mock = port_mock.return_value
        new_port_mock.create.side_effect = side_effect
        trait_mock.return_value = existing_traits

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            result = task.driver.inspect.inspect_hardware(task)

            _inspect_hardware_mock.assert_called_once_with(task.node,
                                                           existing_traits)
            self.assertEqual(2, port_mock.call_count)
            task.node.refresh()
            self.assertEqual(inspected_props, task.node.properties)
            self.assertEqual(states.MANAGEABLE, result)

    @mock.patch.object(objects.trait.TraitList, 'get_trait_names',
                       spec_set=True, autospec=True)
    @mock.patch.object(irmc_inspect, '_get_mac_addresses', spec_set=True,
                       autospec=True)
    @mock.patch.object(irmc_inspect, 'scci',
                       spec_set=mock_specs.SCCICLIENT_IRMC_SCCI_SPEC)
    @mock.patch.object(irmc_common, 'get_irmc_report', spec_set=True,
                       autospec=True)
    def _test_inspect_hardware_props(self, gpu_ids,
                                     fpga_ids,
                                     existed_capabilities,
                                     inspected_capabilities,
                                     expected_capabilities,
                                     existed_traits,
                                     expected_traits,
                                     get_irmc_report_mock,
                                     scci_mock,
                                     _get_mac_addresses_mock,
                                     trait_mock):
        capabilities_props = set(irmc_inspect.CAPABILITIES_PROPERTIES)

        # if gpu_ids = [], pci_gpu_devices will not be inspected
        if len(gpu_ids) == 0:
            capabilities_props.remove('pci_gpu_devices')

        # if fpga_ids = [], cpu_fpga will not be inspected
        if fpga_ids is None or len(fpga_ids) == 0:
            capabilities_props.remove('cpu_fpga')

        self.config(gpu_ids=gpu_ids, group='irmc')
        self.config(fpga_ids=fpga_ids, group='irmc')
        kwargs = {'sleep_flag': False}

        inspected_props = {
            'memory_mb': '1024',
            'local_gb': 10,
            'cpus': 2,
            'cpu_arch': 'x86_64'}

        inspected_macs = ['aa:aa:aa:aa:aa:aa', 'bb:bb:bb:bb:bb:bb']
        report = 'fake_report'

        get_irmc_report_mock.return_value = report
        scci_mock.get_essential_properties.return_value = inspected_props
        scci_mock.get_capabilities_properties.return_value = \
            inspected_capabilities
        _get_mac_addresses_mock.return_value = inspected_macs
        trait_mock.return_value = existed_traits

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            task.node.properties[u'capabilities'] =\
                ",".join('%(k)s:%(v)s' % {'k': k, 'v': v}
                         for k, v in existed_capabilities.items())
            result = irmc_inspect._inspect_hardware(task.node,
                                                    existed_traits,
                                                    **kwargs)
            get_irmc_report_mock.assert_called_once_with(task.node)
            scci_mock.get_essential_properties.assert_called_once_with(
                report, irmc_inspect.IRMCInspect.ESSENTIAL_PROPERTIES)
            scci_mock.get_capabilities_properties.assert_called_once_with(
                mock.ANY, capabilities_props,
                gpu_ids, fpga_ids=fpga_ids, **kwargs)
            expected_capabilities = utils.get_updated_capabilities(
                '', expected_capabilities)

            set1 = set(expected_capabilities.split(','))
            set2 = set(result[0]['capabilities'].split(','))
            self.assertEqual(set1, set2)
            self.assertEqual(expected_traits, result[2])

    def test_inspect_hardware_existing_cap_in_props(self):
        # Set config flags
        gpu_ids = ['0x1000/0x0079', '0x2100/0x0080']
        cpu_fpgas = ['0x1000/0x0179', '0x2100/0x0180']
        existed_capabilities = {
            'trusted_boot': True,
            'irmc_firmware_version': 'iRMC S4-7.82F',
            'server_model': 'TX2540M1F5',
            'rom_firmware_version': 'V4.6.5.4 R1.15.0 for D3099-B1x',
            'pci_gpu_devices': 1
        }
        inspected_capabilities = {
            'trusted_boot': True,
            'irmc_firmware_version': 'iRMC S4-7.82F',
            'server_model': 'TX2540M1F5',
            'rom_firmware_version': 'V4.6.5.4 R1.15.0 for D3099-B1x',
            'pci_gpu_devices': 1,
            'cpu_fpga': 1
        }
        expected_capabilities = {
            'trusted_boot': True,
            'irmc_firmware_version': 'iRMC S4-7.82F',
            'server_model': 'TX2540M1F5',
            'rom_firmware_version': 'V4.6.5.4 R1.15.0 for D3099-B1x',
            'pci_gpu_devices': 1
        }
        existed_traits = []
        expected_traits = ['CUSTOM_CPU_FPGA']

        self._test_inspect_hardware_props(gpu_ids,
                                          cpu_fpgas,
                                          existed_capabilities,
                                          inspected_capabilities,
                                          expected_capabilities,
                                          existed_traits,
                                          expected_traits)

    def test_inspect_hardware_props_empty_gpu_ids_fpga_ids(self):
        # Set config flags
        gpu_ids = []
        cpu_fpgas = []
        existed_capabilities = {}
        inspected_capabilities = {
            'trusted_boot': True,
            'irmc_firmware_version': 'iRMC S4-7.82F',
            'server_model': 'TX2540M1F5',
            'rom_firmware_version': 'V4.6.5.4 R1.15.0 for D3099-B1x'}
        expected_capabilities = {
            'trusted_boot': True,
            'irmc_firmware_version': 'iRMC S4-7.82F',
            'server_model': 'TX2540M1F5',
            'rom_firmware_version': 'V4.6.5.4 R1.15.0 for D3099-B1x'}
        existed_traits = []
        expected_traits = []

        self._test_inspect_hardware_props(gpu_ids,
                                          cpu_fpgas,
                                          existed_capabilities,
                                          inspected_capabilities,
                                          expected_capabilities,
                                          existed_traits,
                                          expected_traits)

    def test_inspect_hardware_props_pci_gpu_devices_return_zero(self):
        # Set config flags
        gpu_ids = ['0x1000/0x0079', '0x2100/0x0080']
        cpu_fpgas = ['0x1000/0x0179', '0x2100/0x0180']
        existed_capabilities = {}
        inspected_capabilities = {
            'trusted_boot': True,
            'irmc_firmware_version': 'iRMC S4-7.82F',
            'server_model': 'TX2540M1F5',
            'rom_firmware_version': 'V4.6.5.4 R1.15.0 for D3099-B1x',
            'pci_gpu_devices': 0,
            'cpu_fpga': 0
        }
        expected_capabilities = {
            'trusted_boot': True,
            'irmc_firmware_version': 'iRMC S4-7.82F',
            'server_model': 'TX2540M1F5',
            'rom_firmware_version': 'V4.6.5.4 R1.15.0 for D3099-B1x'}

        existed_traits = []
        expected_traits = []

        self._test_inspect_hardware_props(gpu_ids,
                                          cpu_fpgas,
                                          existed_capabilities,
                                          inspected_capabilities,
                                          expected_capabilities,
                                          existed_traits,
                                          expected_traits)

    def test_inspect_hardware_props_empty_gpu_ids_fpga_id_sand_existing_cap(
            self):
        # Set config flags
        gpu_ids = []
        cpu_fpgas = []
        existed_capabilities = {
            'trusted_boot': True,
            'irmc_firmware_version': 'iRMC S4-7.82F',
            'server_model': 'TX2540M1F5',
            'rom_firmware_version': 'V4.6.5.4 R1.15.0 for D3099-B1x',
            'pci_gpu_devices': 1}
        inspected_capabilities = {
            'trusted_boot': True,
            'irmc_firmware_version': 'iRMC S4-7.82F',
            'server_model': 'TX2540M1F5',
            'rom_firmware_version': 'V4.6.5.4 R1.15.0 for D3099-B1x'}
        expected_capabilities = {
            'trusted_boot': True,
            'irmc_firmware_version': 'iRMC S4-7.82F',
            'server_model': 'TX2540M1F5',
            'rom_firmware_version': 'V4.6.5.4 R1.15.0 for D3099-B1x'}

        existed_traits = []
        expected_traits = []

        self._test_inspect_hardware_props(gpu_ids,
                                          cpu_fpgas,
                                          existed_capabilities,
                                          inspected_capabilities,
                                          expected_capabilities,
                                          existed_traits,
                                          expected_traits)

    def test_inspect_hardware_props_gpu_cpu_fpgas_zero_and_existing_cap(
            self):
        # Set config flags
        gpu_ids = ['0x1000/0x0079', '0x2100/0x0080']
        cpu_fpgas = ['0x1000/0x0179', '0x2100/0x0180']
        existed_capabilities = {
            'trusted_boot': True,
            'irmc_firmware_version': 'iRMC S4-7.82F',
            'server_model': 'TX2540M1F5',
            'rom_firmware_version': 'V4.6.5.4 R1.15.0 for D3099-B1x',
            'pci_gpu_devices': 1}
        inspected_capabilities = {
            'trusted_boot': True,
            'irmc_firmware_version': 'iRMC S4-7.82F',
            'server_model': 'TX2540M1F5',
            'rom_firmware_version': 'V4.6.5.4 R1.15.0 for D3099-B1x',
            'pci_gpu_devices': 0,
            'cpu_fpga': 0}
        expected_capabilities = {
            'trusted_boot': True,
            'irmc_firmware_version': 'iRMC S4-7.82F',
            'server_model': 'TX2540M1F5',
            'rom_firmware_version': 'V4.6.5.4 R1.15.0 for D3099-B1x'}

        existed_traits = ['CUSTOM_CPU_FPGA']
        expected_traits = []

        self._test_inspect_hardware_props(gpu_ids,
                                          cpu_fpgas,
                                          existed_capabilities,
                                          inspected_capabilities,
                                          expected_capabilities,
                                          existed_traits,
                                          expected_traits)

    def test_inspect_hardware_props_trusted_boot_is_false(self):
        # Set config flags
        gpu_ids = ['0x1000/0x0079', '0x2100/0x0080']
        cpu_fpgas = ['0x1000/0x0179', '0x2100/0x0180']
        existed_capabilities = {}
        inspected_capabilities = {
            'trusted_boot': False,
            'irmc_firmware_version': 'iRMC S4-7.82F',
            'server_model': 'TX2540M1F5',
            'rom_firmware_version': 'V4.6.5.4 R1.15.0 for D3099-B1x',
            'pci_gpu_devices': 1,
            'cpu_fpga': 1}
        expected_capabilities = {
            'irmc_firmware_version': 'iRMC S4-7.82F',
            'server_model': 'TX2540M1F5',
            'rom_firmware_version': 'V4.6.5.4 R1.15.0 for D3099-B1x',
            'pci_gpu_devices': 1}

        existed_traits = []
        expected_traits = ['CUSTOM_CPU_FPGA']

        self._test_inspect_hardware_props(gpu_ids,
                                          cpu_fpgas,
                                          existed_capabilities,
                                          inspected_capabilities,
                                          expected_capabilities,
                                          existed_traits,
                                          expected_traits)

    def test_inspect_hardware_props_trusted_boot_is_false_and_existing_cap(
            self):
        # Set config flags
        gpu_ids = ['0x1000/0x0079', '0x2100/0x0080']
        cpu_fpgas = ['0x1000/0x0179', '0x2100/0x0180']
        existed_capabilities = {
            'trusted_boot': True,
            'irmc_firmware_version': 'iRMC S4-7.82F',
            'server_model': 'TX2540M1F5',
            'rom_firmware_version': 'V4.6.5.4 R1.15.0 for D3099-B1x',
            'pci_gpu_devices': 1}
        inspected_capabilities = {
            'trusted_boot': False,
            'irmc_firmware_version': 'iRMC S4-7.82F',
            'server_model': 'TX2540M1F5',
            'rom_firmware_version': 'V4.6.5.4 R1.15.0 for D3099-B1x',
            'pci_gpu_devices': 1,
            'cpu_fpga': 1}
        expected_capabilities = {
            'irmc_firmware_version': 'iRMC S4-7.82F',
            'server_model': 'TX2540M1F5',
            'rom_firmware_version': 'V4.6.5.4 R1.15.0 for D3099-B1x',
            'pci_gpu_devices': 1}

        existed_traits = ['CUSTOM_CPU_FPGA']
        expected_traits = ['CUSTOM_CPU_FPGA']

        self._test_inspect_hardware_props(gpu_ids,
                                          cpu_fpgas,
                                          existed_capabilities,
                                          inspected_capabilities,
                                          expected_capabilities,
                                          existed_traits,
                                          expected_traits)

    def test_inspect_hardware_props_gpu_and_cpu_fpgas_results_are_different(
            self):
        # Set config flags
        gpu_ids = ['0x1000/0x0079', '0x2100/0x0080']
        cpu_fpgas = ['0x1000/0x0179', '0x2100/0x0180']
        existed_capabilities = {
            'trusted_boot': True,
            'irmc_firmware_version': 'iRMC S4-7.82F',
            'server_model': 'TX2540M1F5',
            'rom_firmware_version': 'V4.6.5.4 R1.15.0 for D3099-B1x',
            'pci_gpu_devices': 1}
        inspected_capabilities = {
            'trusted_boot': False,
            'irmc_firmware_version': 'iRMC S4-7.82F',
            'server_model': 'TX2540M1F5',
            'rom_firmware_version': 'V4.6.5.4 R1.15.0 for D3099-B1x',
            'pci_gpu_devices': 0,
            'cpu_fpga': 1}
        expected_capabilities = {
            'irmc_firmware_version': 'iRMC S4-7.82F',
            'server_model': 'TX2540M1F5',
            'rom_firmware_version': 'V4.6.5.4 R1.15.0 for D3099-B1x'}

        existed_traits = []
        expected_traits = ['CUSTOM_CPU_FPGA']

        self._test_inspect_hardware_props(gpu_ids,
                                          cpu_fpgas,
                                          existed_capabilities,
                                          inspected_capabilities,
                                          expected_capabilities,
                                          existed_traits,
                                          expected_traits)
