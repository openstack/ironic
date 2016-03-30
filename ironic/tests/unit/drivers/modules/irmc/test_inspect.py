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
from ironic.conductor import task_manager
from ironic.drivers.modules.irmc import common as irmc_common
from ironic.drivers.modules.irmc import inspect as irmc_inspect
from ironic import objects
from ironic.tests.unit.conductor import mgr_utils
from ironic.tests.unit.db import base as db_base
from ironic.tests.unit.db import utils as db_utils
from ironic.tests.unit.drivers import third_party_driver_mock_specs \
    as mock_specs
from ironic.tests.unit.objects import utils as obj_utils

INFO_DICT = db_utils.get_test_irmc_info()


class IRMCInspectInternalMethodsTestCase(db_base.DbTestCase):

    def setUp(self):
        super(IRMCInspectInternalMethodsTestCase, self).setUp()
        driver_info = INFO_DICT
        mgr_utils.mock_the_extension_manager(driver='fake_irmc')
        self.node = obj_utils.create_test_node(self.context,
                                               driver='fake_irmc',
                                               driver_info=driver_info)

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
        inspected_props = {
            'memory_mb': '1024',
            'local_gb': 10,
            'cpus': 2,
            'cpu_arch': 'x86_64'}
        inspected_macs = ['aa:aa:aa:aa:aa:aa', 'bb:bb:bb:bb:bb:bb']
        report = 'fake_report'
        get_irmc_report_mock.return_value = report
        scci_mock.get_essential_properties.return_value = inspected_props
        _get_mac_addresses_mock.return_value = inspected_macs
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            result = irmc_inspect._inspect_hardware(task.node)

            get_irmc_report_mock.assert_called_once_with(task.node)
            scci_mock.get_essential_properties.assert_called_once_with(
                report, irmc_inspect.IRMCInspect.ESSENTIAL_PROPERTIES)
            self.assertEqual((inspected_props, inspected_macs), result)

    @mock.patch.object(irmc_inspect, '_get_mac_addresses', spec_set=True,
                       autospec=True)
    @mock.patch.object(irmc_inspect, 'scci',
                       spec_set=mock_specs.SCCICLIENT_IRMC_SCCI_SPEC)
    @mock.patch.object(irmc_common, 'get_irmc_report', spec_set=True,
                       autospec=True)
    def test__inspect_hardware_exception(
            self, get_irmc_report_mock, scci_mock, _get_mac_addresses_mock):
        report = 'fake_report'
        get_irmc_report_mock.return_value = report
        side_effect = exception.SNMPFailure("fake exception")
        scci_mock.get_essential_properties.side_effect = side_effect
        irmc_inspect.scci.SCCIInvalidInputError = Exception
        irmc_inspect.scci.SCCIClientError = Exception

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            self.assertRaises(exception.HardwareInspectionFailure,
                              irmc_inspect._inspect_hardware,
                              task.node)
            get_irmc_report_mock.assert_called_once_with(task.node)
            self.assertFalse(_get_mac_addresses_mock.called)


class IRMCInspectTestCase(db_base.DbTestCase):

    def setUp(self):
        super(IRMCInspectTestCase, self).setUp()
        driver_info = INFO_DICT
        mgr_utils.mock_the_extension_manager(driver="fake_irmc")
        self.node = obj_utils.create_test_node(self.context,
                                               driver='fake_irmc',
                                               driver_info=driver_info)

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
            task.driver.power.validate(task)
            parse_driver_info_mock.assert_called_once_with(task.node)

    @mock.patch.object(irmc_common, 'parse_driver_info', spec_set=True,
                       autospec=True)
    def test_validate_fail(self, parse_driver_info_mock):
        side_effect = exception.InvalidParameterValue("Invalid Input")
        parse_driver_info_mock.side_effect = side_effect

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            self.assertRaises(exception.InvalidParameterValue,
                              task.driver.power.validate,
                              task)

    @mock.patch.object(irmc_inspect.LOG, 'info', spec_set=True, autospec=True)
    @mock.patch('ironic.drivers.modules.irmc.inspect.objects.Port',
                spec_set=True, autospec=True)
    @mock.patch.object(irmc_inspect, '_inspect_hardware', spec_set=True,
                       autospec=True)
    def test_inspect_hardware(self, _inspect_hardware_mock, port_mock,
                              info_mock):
        inspected_props = {
            'memory_mb': '1024',
            'local_gb': 10,
            'cpus': 2,
            'cpu_arch': 'x86_64'}
        inspected_macs = ['aa:aa:aa:aa:aa:aa', 'bb:bb:bb:bb:bb:bb']
        _inspect_hardware_mock.return_value = (inspected_props,
                                               inspected_macs)
        new_port_mock1 = mock.MagicMock(spec=objects.Port)
        new_port_mock2 = mock.MagicMock(spec=objects.Port)

        port_mock.side_effect = [new_port_mock1, new_port_mock2]

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            result = task.driver.inspect.inspect_hardware(task)

            node_id = task.node.id
            _inspect_hardware_mock.assert_called_once_with(task.node)

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

    @mock.patch('ironic.objects.Port', spec_set=True, autospec=True)
    @mock.patch.object(irmc_inspect, '_inspect_hardware', spec_set=True,
                       autospec=True)
    def test_inspect_hardware_inspect_exception(
            self, _inspect_hardware_mock, port_mock):
        side_effect = exception.HardwareInspectionFailure("fake exception")
        _inspect_hardware_mock.side_effect = side_effect

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            self.assertRaises(exception.HardwareInspectionFailure,
                              task.driver.inspect.inspect_hardware,
                              task)
            self.assertFalse(port_mock.called)

    @mock.patch.object(irmc_inspect.LOG, 'warn', spec_set=True, autospec=True)
    @mock.patch('ironic.objects.Port', spec_set=True, autospec=True)
    @mock.patch.object(irmc_inspect, '_inspect_hardware', spec_set=True,
                       autospec=True)
    def test_inspect_hardware_mac_already_exist(
            self, _inspect_hardware_mock, port_mock, warn_mock):
        inspected_props = {
            'memory_mb': '1024',
            'local_gb': 10,
            'cpus': 2,
            'cpu_arch': 'x86_64'}
        inspected_macs = ['aa:aa:aa:aa:aa:aa', 'bb:bb:bb:bb:bb:bb']
        _inspect_hardware_mock.return_value = (inspected_props,
                                               inspected_macs)
        side_effect = exception.MACAlreadyExists("fake exception")
        new_port_mock = port_mock.return_value
        new_port_mock.create.side_effect = side_effect

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            result = task.driver.inspect.inspect_hardware(task)

            _inspect_hardware_mock.assert_called_once_with(task.node)
            self.assertTrue(port_mock.call_count, 2)
            task.node.refresh()
            self.assertEqual(inspected_props, task.node.properties)
            self.assertEqual(states.MANAGEABLE, result)
