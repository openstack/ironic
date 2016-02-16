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

"""Test class for VirtualBox Driver Modules."""

import mock
from pyremotevbox import exception as pyremotevbox_exc
from pyremotevbox import vbox as pyremotevbox_vbox

from ironic.common import boot_devices
from ironic.common import exception
from ironic.common import states
from ironic.conductor import task_manager
from ironic.drivers.modules import virtualbox
from ironic.tests.unit.conductor import mgr_utils
from ironic.tests.unit.db import base as db_base
from ironic.tests.unit.objects import utils as obj_utils

INFO_DICT = {
    'virtualbox_vmname': 'baremetal1',
    'virtualbox_host': '10.0.2.2',
    'virtualbox_username': 'username',
    'virtualbox_password': 'password',
    'virtualbox_port': 12345,
}


class VirtualBoxMethodsTestCase(db_base.DbTestCase):

    def setUp(self):
        super(VirtualBoxMethodsTestCase, self).setUp()
        driver_info = INFO_DICT.copy()
        mgr_utils.mock_the_extension_manager(driver="fake_vbox")
        self.node = obj_utils.create_test_node(self.context,
                                               driver='fake_vbox',
                                               driver_info=driver_info)

    def test__parse_driver_info(self):
        info = virtualbox._parse_driver_info(self.node)
        self.assertEqual('baremetal1', info['vmname'])
        self.assertEqual('10.0.2.2', info['host'])
        self.assertEqual('username', info['username'])
        self.assertEqual('password', info['password'])
        self.assertEqual(12345, info['port'])

    def test__parse_driver_info_missing_vmname(self):
        del self.node.driver_info['virtualbox_vmname']
        self.assertRaises(exception.MissingParameterValue,
                          virtualbox._parse_driver_info, self.node)

    def test__parse_driver_info_missing_host(self):
        del self.node.driver_info['virtualbox_host']
        self.assertRaises(exception.MissingParameterValue,
                          virtualbox._parse_driver_info, self.node)

    def test__parse_driver_info_invalid_port(self):
        self.node.driver_info['virtualbox_port'] = 'invalid-port'
        self.assertRaises(exception.InvalidParameterValue,
                          virtualbox._parse_driver_info, self.node)

    def test__parse_driver_info_missing_port(self):
        del self.node.driver_info['virtualbox_port']
        info = virtualbox._parse_driver_info(self.node)
        self.assertEqual(18083, info['port'])

    @mock.patch.object(pyremotevbox_vbox, 'VirtualBoxHost', autospec=True)
    def test__run_virtualbox_method(self, host_mock):
        host_object_mock = mock.MagicMock(spec_set=['find_vm'])
        func_mock = mock.MagicMock(spec_set=[])
        vm_object_mock = mock.MagicMock(spec_set=['foo'], foo=func_mock)
        host_mock.return_value = host_object_mock
        host_object_mock.find_vm.return_value = vm_object_mock
        func_mock.return_value = 'return-value'

        return_value = virtualbox._run_virtualbox_method(
            self.node, 'some-ironic-method', 'foo', 'args', kwarg='kwarg')

        host_mock.assert_called_once_with(vmname='baremetal1',
                                          host='10.0.2.2',
                                          username='username',
                                          password='password',
                                          port=12345)
        host_object_mock.find_vm.assert_called_once_with('baremetal1')
        func_mock.assert_called_once_with('args', kwarg='kwarg')
        self.assertEqual('return-value', return_value)

    @mock.patch.object(pyremotevbox_vbox, 'VirtualBoxHost', autospec=True)
    def test__run_virtualbox_method_get_host_fails(self, host_mock):
        host_mock.side_effect = pyremotevbox_exc.PyRemoteVBoxException

        self.assertRaises(exception.VirtualBoxOperationFailed,
                          virtualbox._run_virtualbox_method,
                          self.node, 'some-ironic-method', 'foo',
                          'args', kwarg='kwarg')

    @mock.patch.object(pyremotevbox_vbox, 'VirtualBoxHost', autospec=True)
    def test__run_virtualbox_method_find_vm_fails(self, host_mock):
        host_object_mock = mock.MagicMock(spec_set=['find_vm'])
        host_mock.return_value = host_object_mock
        exc = pyremotevbox_exc.PyRemoteVBoxException
        host_object_mock.find_vm.side_effect = exc

        self.assertRaises(exception.VirtualBoxOperationFailed,
                          virtualbox._run_virtualbox_method,
                          self.node, 'some-ironic-method', 'foo', 'args',
                          kwarg='kwarg')
        host_mock.assert_called_once_with(vmname='baremetal1',
                                          host='10.0.2.2',
                                          username='username',
                                          password='password',
                                          port=12345)
        host_object_mock.find_vm.assert_called_once_with('baremetal1')

    @mock.patch.object(pyremotevbox_vbox, 'VirtualBoxHost', autospec=True)
    def test__run_virtualbox_method_func_fails(self, host_mock):
        host_object_mock = mock.MagicMock(spec_set=['find_vm'])
        host_mock.return_value = host_object_mock
        func_mock = mock.MagicMock()
        vm_object_mock = mock.MagicMock(spec_set=['foo'], foo=func_mock)
        host_object_mock.find_vm.return_value = vm_object_mock
        func_mock.side_effect = pyremotevbox_exc.PyRemoteVBoxException

        self.assertRaises(exception.VirtualBoxOperationFailed,
                          virtualbox._run_virtualbox_method,
                          self.node, 'some-ironic-method', 'foo',
                          'args', kwarg='kwarg')
        host_mock.assert_called_once_with(vmname='baremetal1',
                                          host='10.0.2.2',
                                          username='username',
                                          password='password',
                                          port=12345)
        host_object_mock.find_vm.assert_called_once_with('baremetal1')
        func_mock.assert_called_once_with('args', kwarg='kwarg')

    @mock.patch.object(pyremotevbox_vbox, 'VirtualBoxHost', autospec=True)
    def test__run_virtualbox_method_invalid_method(self, host_mock):
        host_object_mock = mock.MagicMock(spec_set=['find_vm'])
        host_mock.return_value = host_object_mock
        vm_object_mock = mock.MagicMock(spec_set=[])
        host_object_mock.find_vm.return_value = vm_object_mock
        del vm_object_mock.foo

        self.assertRaises(exception.InvalidParameterValue,
                          virtualbox._run_virtualbox_method,
                          self.node, 'some-ironic-method', 'foo',
                          'args', kwarg='kwarg')
        host_mock.assert_called_once_with(vmname='baremetal1',
                                          host='10.0.2.2',
                                          username='username',
                                          password='password',
                                          port=12345)
        host_object_mock.find_vm.assert_called_once_with('baremetal1')

    @mock.patch.object(pyremotevbox_vbox, 'VirtualBoxHost', autospec=True)
    def test__run_virtualbox_method_vm_wrong_power_state(self, host_mock):
        host_object_mock = mock.MagicMock(spec_set=['find_vm'])
        host_mock.return_value = host_object_mock
        func_mock = mock.MagicMock(spec_set=[])
        vm_object_mock = mock.MagicMock(spec_set=['foo'], foo=func_mock)
        host_object_mock.find_vm.return_value = vm_object_mock
        func_mock.side_effect = pyremotevbox_exc.VmInWrongPowerState

        # _run_virtualbox_method() doesn't catch VmInWrongPowerState and
        # lets caller handle it.
        self.assertRaises(pyremotevbox_exc.VmInWrongPowerState,
                          virtualbox._run_virtualbox_method,
                          self.node, 'some-ironic-method', 'foo',
                          'args', kwarg='kwarg')
        host_mock.assert_called_once_with(vmname='baremetal1',
                                          host='10.0.2.2',
                                          username='username',
                                          password='password',
                                          port=12345)
        host_object_mock.find_vm.assert_called_once_with('baremetal1')
        func_mock.assert_called_once_with('args', kwarg='kwarg')


class VirtualBoxPowerTestCase(db_base.DbTestCase):

    def setUp(self):
        super(VirtualBoxPowerTestCase, self).setUp()
        driver_info = INFO_DICT.copy()
        mgr_utils.mock_the_extension_manager(driver="fake_vbox")
        self.node = obj_utils.create_test_node(self.context,
                                               driver='fake_vbox',
                                               driver_info=driver_info)

    def test_get_properties(self):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            properties = task.driver.power.get_properties()

        self.assertIn('virtualbox_vmname', properties)
        self.assertIn('virtualbox_host', properties)

    @mock.patch.object(virtualbox, '_parse_driver_info', autospec=True)
    def test_validate(self, parse_info_mock):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.driver.power.validate(task)
            parse_info_mock.assert_called_once_with(task.node)

    @mock.patch.object(virtualbox, '_run_virtualbox_method', autospec=True)
    def test_get_power_state(self, run_method_mock):
        run_method_mock.return_value = 'PoweredOff'
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            power_state = task.driver.power.get_power_state(task)
            run_method_mock.assert_called_once_with(task.node,
                                                    'get_power_state',
                                                    'get_power_status')
            self.assertEqual(states.POWER_OFF, power_state)

    @mock.patch.object(virtualbox, '_run_virtualbox_method', autospec=True)
    def test_get_power_state_invalid_state(self, run_method_mock):
        run_method_mock.return_value = 'invalid-state'
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            power_state = task.driver.power.get_power_state(task)
            run_method_mock.assert_called_once_with(task.node,
                                                    'get_power_state',
                                                    'get_power_status')
            self.assertEqual(states.ERROR, power_state)

    @mock.patch.object(virtualbox, '_run_virtualbox_method', autospec=True)
    def test_set_power_state_off(self, run_method_mock):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.driver.power.set_power_state(task, states.POWER_OFF)
            run_method_mock.assert_called_once_with(task.node,
                                                    'set_power_state',
                                                    'stop')

    @mock.patch.object(virtualbox.VirtualBoxManagement, 'set_boot_device')
    @mock.patch.object(virtualbox, '_run_virtualbox_method', autospec=True)
    def test_set_power_state_on(self, run_method_mock, set_boot_device_mock):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.node.driver_internal_info['vbox_target_boot_device'] = 'pxe'
            task.driver.power.set_power_state(task, states.POWER_ON)
            run_method_mock.assert_called_once_with(task.node,
                                                    'set_power_state',
                                                    'start')
            set_boot_device_mock.assert_called_once_with(task, 'pxe')

    @mock.patch.object(virtualbox.VirtualBoxManagement, 'set_boot_device')
    @mock.patch.object(virtualbox, '_run_virtualbox_method', autospec=True)
    def test_set_power_state_reboot(self, run_method_mock,
                                    mock_set_boot_device):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.node.driver_internal_info['vbox_target_boot_device'] = 'pxe'
            task.driver.power.set_power_state(task, states.REBOOT)
            run_method_mock.assert_any_call(task.node,
                                            'reboot',
                                            'stop')
            mock_set_boot_device.assert_called_once_with(task, 'pxe')
            run_method_mock.assert_any_call(task.node,
                                            'reboot',
                                            'start')

    def test_set_power_state_invalid_state(self):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            self.assertRaises(exception.InvalidParameterValue,
                              task.driver.power.set_power_state,
                              task, 'invalid-state')

    @mock.patch.object(virtualbox, '_run_virtualbox_method', autospec=True)
    def test_reboot(self, run_method_mock):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.driver.power.reboot(task)
            run_method_mock.assert_any_call(task.node,
                                            'reboot',
                                            'stop')
            run_method_mock.assert_any_call(task.node,
                                            'reboot',
                                            'start')


class VirtualBoxManagementTestCase(db_base.DbTestCase):

    def setUp(self):
        super(VirtualBoxManagementTestCase, self).setUp()
        driver_info = INFO_DICT.copy()
        mgr_utils.mock_the_extension_manager(driver="fake_vbox")
        self.node = obj_utils.create_test_node(self.context,
                                               driver='fake_vbox',
                                               driver_info=driver_info)

    def test_get_properties(self):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            properties = task.driver.management.get_properties()

        self.assertIn('virtualbox_vmname', properties)
        self.assertIn('virtualbox_host', properties)

    @mock.patch.object(virtualbox, '_parse_driver_info', autospec=True)
    def test_validate(self, parse_info_mock):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.driver.management.validate(task)
            parse_info_mock.assert_called_once_with(task.node)

    def test_get_supported_boot_devices(self):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            devices = task.driver.management.get_supported_boot_devices(task)
            self.assertIn(boot_devices.PXE, devices)
            self.assertIn(boot_devices.DISK, devices)
            self.assertIn(boot_devices.CDROM, devices)

    @mock.patch.object(virtualbox.VirtualBoxPower,
                       'get_power_state', autospec=True)
    @mock.patch.object(virtualbox, '_run_virtualbox_method',
                       autospec=True)
    def test_get_boot_device_VM_Poweroff_ok(self, run_method_mock,
                                            get_power_state_mock):
        run_method_mock.return_value = 'Network'
        get_power_state_mock.return_value = states.POWER_OFF
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            ret_val = task.driver.management.get_boot_device(task)
            run_method_mock.assert_called_once_with(task.node,
                                                    'get_boot_device',
                                                    'get_boot_device')
            self.assertEqual(boot_devices.PXE, ret_val['boot_device'])
            self.assertTrue(ret_val['persistent'])

    @mock.patch.object(virtualbox.VirtualBoxPower,
                       'get_power_state', autospec=True)
    def test_get_boot_device_VM_Poweron_ok(self, get_power_state_mock):
        get_power_state_mock.return_value = states.POWER_ON
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.node.driver_internal_info['vbox_target_boot_device'] = 'pxe'
            ret_val = task.driver.management.get_boot_device(task)
            self.assertEqual(boot_devices.PXE, ret_val['boot_device'])
            self.assertTrue(ret_val['persistent'])

    @mock.patch.object(virtualbox.VirtualBoxPower,
                       'get_power_state', autospec=True)
    @mock.patch.object(virtualbox, '_run_virtualbox_method',
                       autospec=True)
    def test_get_boot_device_target_device_none_ok(self,
                                                   run_method_mock,
                                                   get_power_state_mock):
        run_method_mock.return_value = 'Network'
        get_power_state_mock.return_value = states.POWER_ON
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.node.driver_internal_info['vbox_target_boot_device'] = None
            ret_val = task.driver.management.get_boot_device(task)
            run_method_mock.assert_called_once_with(task.node,
                                                    'get_boot_device',
                                                    'get_boot_device')
            self.assertEqual(boot_devices.PXE, ret_val['boot_device'])
            self.assertTrue(ret_val['persistent'])

    @mock.patch.object(virtualbox, '_run_virtualbox_method', autospec=True)
    def test_get_boot_device_invalid(self, run_method_mock):
        run_method_mock.return_value = 'invalid-boot-device'
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            ret_val = task.driver.management.get_boot_device(task)
            self.assertIsNone(ret_val['boot_device'])
            self.assertIsNone(ret_val['persistent'])

    @mock.patch.object(virtualbox.VirtualBoxPower,
                       'get_power_state', autospec=True)
    @mock.patch.object(virtualbox, '_run_virtualbox_method', autospec=True)
    def test_set_boot_device_VM_Poweroff_ok(self, run_method_mock,
                                            get_power_state_mock):
        get_power_state_mock.return_value = states.POWER_OFF
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.driver.management.set_boot_device(task, boot_devices.PXE)
            run_method_mock.assert_called_with(task.node,
                                               'set_boot_device',
                                               'set_boot_device',
                                               'Network')

    @mock.patch.object(virtualbox.VirtualBoxPower,
                       'get_power_state', autospec=True)
    @mock.patch.object(virtualbox, '_run_virtualbox_method', autospec=True)
    def test_set_boot_device_VM_Poweron_ok(self, run_method_mock,
                                           get_power_state_mock):
        get_power_state_mock.return_value = states.POWER_ON
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.driver.management.set_boot_device(task, boot_devices.PXE)
            self.assertEqual('pxe',
                             task.node.driver_internal_info
                             ['vbox_target_boot_device'])

    @mock.patch.object(virtualbox, '_run_virtualbox_method', autospec=True)
    def test_set_boot_device_invalid(self, run_method_mock):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            self.assertRaises(exception.InvalidParameterValue,
                              task.driver.management.set_boot_device,
                              task, 'invalid-boot-device')

    def test_get_sensors_data(self):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            self.assertRaises(NotImplementedError,
                              task.driver.management.get_sensors_data,
                              task)
