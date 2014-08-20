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

"""Test class for Ironic SeaMicro driver."""

import uuid

import mock
from seamicroclient import client as seamicro_client
from seamicroclient import exceptions as seamicro_client_exception

from ironic.common import boot_devices
from ironic.common import driver_factory
from ironic.common import exception
from ironic.common import states
from ironic.common import utils
from ironic.conductor import task_manager
from ironic.db import api as dbapi
from ironic.drivers.modules import seamicro
from ironic.openstack.common import context
from ironic.tests import base
from ironic.tests.conductor import utils as mgr_utils
from ironic.tests.db import base as db_base
from ironic.tests.db import utils as db_utils
from ironic.tests.objects import utils as obj_utils

INFO_DICT = db_utils.get_test_seamicro_info()


class Fake_Server():
    def __init__(self, active=False, *args, **kwargs):
        self.active = active
        self.nic = {'0': {'untaggedVlan': ''}}

    def power_on(self):
        self.active = True

    def power_off(self, force=False):
        self.active = False

    def reset(self):
        self.active = True

    def set_untagged_vlan(self, vlan_id):
        return

    def attach_volume(self, volume_id):
        return

    def detach_volume(self):
        return

    def set_boot_order(self, boot_order):
        return

    def refresh(self, wait=0):
        return self


class Fake_Volume():
    def __init__(self, id=None, *args, **kwargs):
        if id is None:
            self.id = "%s/%s/%s" % ("0", "ironic-p6-6", str(uuid.uuid4()))
        else:
            self.id = id


class Fake_Pool():
    def __init__(self, freeSize=None, *args, **kwargs):
        self.freeSize = freeSize


class SeaMicroValidateParametersTestCase(base.TestCase):
    def setUp(self):
        super(SeaMicroValidateParametersTestCase, self).setUp()
        self.context = context.get_admin_context()

    def test__parse_driver_info_good(self):
        # make sure we get back the expected things
        node = obj_utils.get_test_node(
                self.context,
                driver='fake_seamicro',
                driver_info=INFO_DICT)
        info = seamicro._parse_driver_info(node)
        self.assertIsNotNone(info.get('api_endpoint'))
        self.assertIsNotNone(info.get('username'))
        self.assertIsNotNone(info.get('password'))
        self.assertIsNotNone(info.get('server_id'))
        self.assertIsNotNone(info.get('uuid'))

    def test__parse_driver_info_missing_api_endpoint(self):
        # make sure error is raised when info is missing
        info = dict(INFO_DICT)
        del info['seamicro_api_endpoint']
        node = obj_utils.get_test_node(self.context, driver_info=info)
        self.assertRaises(exception.MissingParameterValue,
                          seamicro._parse_driver_info,
                          node)

    def test__parse_driver_info_missing_username(self):
        # make sure error is raised when info is missing
        info = dict(INFO_DICT)
        del info['seamicro_username']
        node = obj_utils.get_test_node(self.context, driver_info=info)
        self.assertRaises(exception.MissingParameterValue,
                          seamicro._parse_driver_info,
                          node)

    def test__parse_driver_info_missing_password(self):
        # make sure error is raised when info is missing
        info = dict(INFO_DICT)
        del info['seamicro_password']
        node = obj_utils.get_test_node(self.context, driver_info=info)
        self.assertRaises(exception.MissingParameterValue,
                          seamicro._parse_driver_info,
                          node)

    def test__parse_driver_info_missing_server_id(self):
        # make sure error is raised when info is missing
        info = dict(INFO_DICT)
        del info['seamicro_server_id']
        node = obj_utils.get_test_node(self.context, driver_info=info)
        self.assertRaises(exception.MissingParameterValue,
                          seamicro._parse_driver_info,
                          node)


class SeaMicroPrivateMethodsTestCase(base.TestCase):

    def setUp(self):
        super(SeaMicroPrivateMethodsTestCase, self).setUp()
        n = {
            'driver': 'fake_seamicro',
            'driver_info': INFO_DICT
        }
        self.context = context.get_admin_context()
        self.dbapi = dbapi.get_instance()
        self.node = obj_utils.create_test_node(self.context, **n)
        self.Server = Fake_Server
        self.Volume = Fake_Volume
        self.Pool = Fake_Pool
        self.config(action_timeout=0, group='seamicro')
        self.config(max_retry=2, group='seamicro')

        self.patcher = mock.patch('eventlet.greenthread.sleep')
        self.mock_sleep = self.patcher.start()

    @mock.patch.object(seamicro_client, "Client")
    def test__get_client(self, mock_client):
        driver_info = seamicro._parse_driver_info(self.node)
        args = {'username': driver_info['username'],
                'password': driver_info['password'],
                'auth_url': driver_info['api_endpoint']}
        seamicro._get_client(**driver_info)
        mock_client.assert_called_once_with(driver_info['api_version'], **args)

    @mock.patch.object(seamicro_client, "Client")
    def test__get_client_fail(self, mock_client):
        driver_info = seamicro._parse_driver_info(self.node)
        args = {'username': driver_info['username'],
                'password': driver_info['password'],
                'auth_url': driver_info['api_endpoint']}
        mock_client.side_effect = seamicro_client_exception.UnsupportedVersion
        self.assertRaises(exception.InvalidParameterValue,
                          seamicro._get_client,
                          **driver_info)
        mock_client.assert_called_once_with(driver_info['api_version'], **args)

    @mock.patch.object(seamicro, "_get_server")
    def test__get_power_status_on(self, mock_get_server):
        mock_get_server.return_value = self.Server(active=True)
        pstate = seamicro._get_power_status(self.node)
        self.assertEqual(states.POWER_ON, pstate)

    @mock.patch.object(seamicro, "_get_server")
    def test__get_power_status_off(self, mock_get_server):
        mock_get_server.return_value = self.Server(active=False)
        pstate = seamicro._get_power_status(self.node)
        self.assertEqual(states.POWER_OFF, pstate)

    @mock.patch.object(seamicro, "_get_server")
    def test__get_power_status_error(self, mock_get_server):
        mock_get_server.return_value = self.Server(active=None)
        pstate = seamicro._get_power_status(self.node)
        self.assertEqual(states.ERROR, pstate)

    @mock.patch.object(seamicro, "_get_server")
    def test__power_on_good(self, mock_get_server):
        mock_get_server.return_value = self.Server(active=False)
        pstate = seamicro._power_on(self.node)
        self.assertEqual(states.POWER_ON, pstate)

    @mock.patch.object(seamicro, "_get_server")
    def test__power_on_fail(self, mock_get_server):
        def fake_power_on():
            return

        server = self.Server(active=False)
        server.power_on = fake_power_on
        mock_get_server.return_value = server
        pstate = seamicro._power_on(self.node)
        self.assertEqual(states.ERROR, pstate)

    @mock.patch.object(seamicro, "_get_server")
    def test__power_off_good(self, mock_get_server):
        mock_get_server.return_value = self.Server(active=True)
        pstate = seamicro._power_off(self.node)
        self.assertEqual(states.POWER_OFF, pstate)

    @mock.patch.object(seamicro, "_get_server")
    def test__power_off_fail(self, mock_get_server):
        def fake_power_off():
            return
        server = self.Server(active=True)
        server.power_off = fake_power_off
        mock_get_server.return_value = server
        pstate = seamicro._power_off(self.node)
        self.assertEqual(states.ERROR, pstate)

    @mock.patch.object(seamicro, "_get_server")
    def test__reboot_good(self, mock_get_server):
        mock_get_server.return_value = self.Server(active=True)
        pstate = seamicro._reboot(self.node)
        self.assertEqual(states.POWER_ON, pstate)

    @mock.patch.object(seamicro, "_get_server")
    def test__reboot_fail(self, mock_get_server):
        def fake_reboot():
            return
        server = self.Server(active=False)
        server.reset = fake_reboot
        mock_get_server.return_value = server
        pstate = seamicro._reboot(self.node)
        self.assertEqual(states.ERROR, pstate)

    @mock.patch.object(seamicro, "_get_volume")
    def test__validate_fail(self, mock_get_volume):
        info = seamicro._parse_driver_info(self.node)
        volume_id = "0/p6-6/vol1"
        volume = self.Volume()
        volume.id = volume_id
        mock_get_volume.return_value = volume
        self.assertRaises(exception.InvalidParameterValue,
                          seamicro._validate_volume, info, volume_id)

    @mock.patch.object(seamicro, "_get_volume")
    def test__validate_good(self, mock_get_volume):
        info = seamicro._parse_driver_info(self.node)
        volume = self.Volume()
        mock_get_volume.return_value = volume
        valid = seamicro._validate_volume(info, volume.id)
        self.assertEqual(valid, True)

    @mock.patch.object(seamicro, "_get_pools")
    def test__create_volume_fail(self, mock_get_pools):
        info = seamicro._parse_driver_info(self.node)
        mock_get_pools.return_value = None
        self.assertRaises(exception.IronicException,
                          seamicro._create_volume,
                          info, 2)

    @mock.patch.object(seamicro, "_get_pools")
    @mock.patch.object(seamicro, "_get_client")
    def test__create_volume_good(self, mock_get_client, mock_get_pools):
        info = seamicro._parse_driver_info(self.node)
        pools = [self.Pool(1), self.Pool(6), self.Pool(5)]
        get_pools_patcher = mock.patch.object(mock_get_client, "volume.create")
        get_pools_patcher.start()
        mock_get_pools.return_value = pools
        seamicro._create_volume(info, 2)
        get_pools_patcher.stop()


class SeaMicroPowerDriverTestCase(db_base.DbTestCase):

    def setUp(self):
        super(SeaMicroPowerDriverTestCase, self).setUp()
        mgr_utils.mock_the_extension_manager(driver='fake_seamicro')
        self.driver = driver_factory.get_driver('fake_seamicro')
        self.node = obj_utils.create_test_node(self.context,
                                               driver='fake_seamicro',
                                               driver_info=INFO_DICT)
        self.dbapi = dbapi.get_instance()
        self.get_server_patcher = mock.patch.object(seamicro, '_get_server')

        self.get_server_mock = None
        self.Server = Fake_Server
        self.Volume = Fake_Volume

    def test_get_properties(self):
        expected = seamicro.COMMON_PROPERTIES
        with task_manager.acquire(self.context, self.node['uuid'],
                                  shared=True) as task:
            self.assertEqual(expected, task.driver.get_properties())

    @mock.patch.object(seamicro, '_parse_driver_info')
    def test_power_interface_validate_good(self, parse_drv_info_mock):
        with task_manager.acquire(self.context, self.node['uuid'],
                                  shared=True) as task:
            task.driver.power.validate(task)
        self.assertEqual(1, parse_drv_info_mock.call_count)

    @mock.patch.object(seamicro, '_parse_driver_info')
    def test_power_interface_validate_fails(self, parse_drv_info_mock):
        side_effect = exception.InvalidParameterValue("Bad input")
        parse_drv_info_mock.side_effect = side_effect
        with task_manager.acquire(self.context, self.node['uuid'],
                                  shared=True) as task:
            self.assertRaises(exception.InvalidParameterValue,
                              task.driver.power.validate, task)
        self.assertEqual(1, parse_drv_info_mock.call_count)

    @mock.patch.object(seamicro, '_reboot')
    def test_reboot(self, mock_reboot):
        info = seamicro._parse_driver_info(self.node)

        mock_reboot.return_value = states.POWER_ON

        with task_manager.acquire(self.context, info['uuid'],
                                  shared=False) as task:
            task.driver.power.reboot(task)

            mock_reboot.assert_called_once_with(task.node)

    def test_set_power_state_bad_state(self):
        info = seamicro ._parse_driver_info(self.node)
        self.get_server_mock = self.get_server_patcher.start()
        self.get_server_mock.return_value = self.Server()

        with task_manager.acquire(self.context, info['uuid'],
                                  shared=False) as task:
            self.assertRaises(exception.IronicException,
                              task.driver.power.set_power_state,
                              task, "BAD_PSTATE")
        self.get_server_patcher.stop()

    @mock.patch.object(seamicro, '_power_on')
    def test_set_power_state_on_good(self, mock_power_on):
        info = seamicro._parse_driver_info(self.node)

        mock_power_on.return_value = states.POWER_ON

        with task_manager.acquire(self.context, info['uuid'],
                                  shared=False) as task:
            task.driver.power.set_power_state(task, states.POWER_ON)

            mock_power_on.assert_called_once_with(task.node)

    @mock.patch.object(seamicro, '_power_on')
    def test_set_power_state_on_fail(self, mock_power_on):
        info = seamicro._parse_driver_info(self.node)

        mock_power_on.return_value = states.POWER_OFF

        with task_manager.acquire(self.context, info['uuid'],
                                  shared=False) as task:
            self.assertRaises(exception.PowerStateFailure,
                              task.driver.power.set_power_state,
                              task, states.POWER_ON)

            mock_power_on.assert_called_once_with(task.node)

    @mock.patch.object(seamicro, '_power_off')
    def test_set_power_state_off_good(self, mock_power_off):
        info = seamicro._parse_driver_info(self.node)

        mock_power_off.return_value = states.POWER_OFF

        with task_manager.acquire(self.context, info['uuid'],
                                  shared=False) as task:
            task.driver.power.set_power_state(task, states.POWER_OFF)

            mock_power_off.assert_called_once_with(task.node)

    @mock.patch.object(seamicro, '_power_off')
    def test_set_power_state_off_fail(self, mock_power_off):
        info = seamicro._parse_driver_info(self.node)

        mock_power_off.return_value = states.POWER_ON

        with task_manager.acquire(self.context, info['uuid'],
                                  shared=False) as task:
            self.assertRaises(exception.PowerStateFailure,
                              task.driver.power.set_power_state,
                              task, states.POWER_OFF)

            mock_power_off.assert_called_once_with(task.node)

    @mock.patch.object(seamicro, '_parse_driver_info')
    def test_vendor_passthru_validate_good(self, mock_info):
        with task_manager.acquire(self.context, self.node['uuid'],
                                  shared=True) as task:
            for method in seamicro.VENDOR_PASSTHRU_METHODS:
                task.driver.vendor.validate(task, **{'method': method})
            self.assertEqual(len(seamicro.VENDOR_PASSTHRU_METHODS),
                             mock_info.call_count)

    @mock.patch.object(seamicro, '_parse_driver_info')
    def test_vendor_passthru_validate_fail(self, mock_info):
        with task_manager.acquire(self.context, self.node['uuid'],
                                  shared=True) as task:
            self.assertRaises(exception.InvalidParameterValue,
                              task.driver.vendor.validate,
                              task, **{'method': 'invalid_method'})
            self.assertFalse(mock_info.called)

    @mock.patch.object(seamicro, '_parse_driver_info')
    def test_vendor_passthru_validate_parse_driver_info_fail(self, mock_info):
        mock_info.side_effect = exception.InvalidParameterValue("bad")
        with task_manager.acquire(self.context, self.node['uuid'],
                                  shared=True) as task:
            method = seamicro.VENDOR_PASSTHRU_METHODS[0]
            self.assertRaises(exception.InvalidParameterValue,
                              task.driver.vendor.validate,
                              task, **{'method': method})
            mock_info.assert_called_once_with(task.node)

    @mock.patch.object(seamicro, '_get_server')
    def test_set_node_vlan_id_good(self, mock_get_server):
        info = seamicro._parse_driver_info(self.node)
        vlan_id = "12"
        mock_get_server.return_value = self.Server(active="true")
        with task_manager.acquire(self.context, info['uuid'],
                                  shared=False) as task:
            kwargs = {'vlan_id': vlan_id, 'method': 'set_node_vlan_id'}
            task.driver.vendor.vendor_passthru(task, **kwargs)
        mock_get_server.assert_called_once_with(info)

    def test_set_node_vlan_id_no_input(self):
        info = seamicro._parse_driver_info(self.node)
        with task_manager.acquire(self.context, info['uuid'],
                                  shared=False) as task:
            self.assertRaises(exception.InvalidParameterValue,
                              task.driver.vendor.vendor_passthru,
                              task,
                              **{'method': 'set_node_vlan_id'})

    @mock.patch.object(seamicro, '_get_server')
    def test_set_node_vlan_id_fail(self, mock_get_server):
        def fake_set_untagged_vlan(self, **kwargs):
            raise seamicro_client_exception.ClientException(500)

        info = seamicro._parse_driver_info(self.node)
        vlan_id = "12"
        server = self.Server(active="true")
        server.set_untagged_vlan = fake_set_untagged_vlan
        mock_get_server.return_value = server
        with task_manager.acquire(self.context, info['uuid'],
                                  shared=False) as task:
            kwargs = {'vlan_id': vlan_id, 'method': 'set_node_vlan_id'}
            self.assertRaises(exception.IronicException,
                              task.driver.vendor.vendor_passthru,
                              task,
                              **kwargs)

        mock_get_server.assert_called_once_with(info)

    @mock.patch.object(seamicro, '_get_server')
    @mock.patch.object(seamicro, '_validate_volume')
    def test_attach_volume_with_volume_id_good(self, mock_validate_volume,
                                               mock_get_server):
        info = seamicro._parse_driver_info(self.node)
        volume_id = '0/ironic-p6-1/vol1'
        mock_validate_volume.return_value = True
        mock_get_server.return_value = self.Server(active="true")
        with task_manager.acquire(self.context, info['uuid'],
                                  shared=False) as task:
            kwargs = {'volume_id': volume_id, 'method': 'attach_volume'}
            task.driver.vendor.vendor_passthru(task, **kwargs)
        mock_get_server.assert_called_once_with(info)

    @mock.patch.object(seamicro, '_get_server')
    @mock.patch.object(seamicro, '_get_volume')
    def test_attach_volume_with_invalid_volume_id_fail(self,
                                                       mock_get_volume,
                                                       mock_get_server):
        info = seamicro._parse_driver_info(self.node)
        volume_id = '0/p6-1/vol1'
        mock_get_volume.return_value = self.Volume(volume_id)
        mock_get_server.return_value = self.Server(active="true")
        with task_manager.acquire(self.context, info['uuid'],
                                  shared=False) as task:
            kwargs = {'volume_id': volume_id, 'method': 'attach_volume'}
            self.assertRaises(exception.InvalidParameterValue,
                              task.driver.vendor.vendor_passthru,
                              task,
                              **kwargs)

    @mock.patch.object(seamicro, '_get_server')
    @mock.patch.object(seamicro, '_validate_volume')
    def test_attach_volume_fail(self, mock_validate_volume,
                                mock_get_server):
        def fake_attach_volume(self, **kwargs):
            raise seamicro_client_exception.ClientException(500)

        info = seamicro._parse_driver_info(self.node)
        volume_id = '0/p6-1/vol1'
        mock_validate_volume.return_value = True
        server = self.Server(active="true")
        server.attach_volume = fake_attach_volume
        mock_get_server.return_value = server
        with task_manager.acquire(self.context, info['uuid'],
                                  shared=False) as task:
            kwargs = {'volume_id': volume_id, 'method': 'attach_volume'}
            self.assertRaises(exception.IronicException,
                              task.driver.vendor.vendor_passthru,
                              task,
                              **kwargs)

        mock_get_server.assert_called_once_with(info)

    @mock.patch.object(seamicro, '_get_server')
    @mock.patch.object(seamicro, '_validate_volume')
    @mock.patch.object(seamicro, '_create_volume')
    def test_attach_volume_with_volume_size_good(self, mock_create_volume,
                                                 mock_validate_volume,
                                                 mock_get_server):
        info = seamicro._parse_driver_info(self.node)
        volume_id = '0/ironic-p6-1/vol1'
        volume_size = 2
        mock_create_volume.return_value = volume_id
        mock_validate_volume.return_value = True
        mock_get_server.return_value = self.Server(active="true")
        with task_manager.acquire(self.context, info['uuid'],
                                  shared=False) as task:
            kwargs = {'volume_size': volume_size, 'method': "attach_volume"}
            task.driver.vendor.vendor_passthru(task, **kwargs)
        mock_get_server.assert_called_once_with(info)
        mock_create_volume.assert_called_once_with(info, volume_size)

    def test_attach_volume_with_no_input_fail(self):
        info = seamicro._parse_driver_info(self.node)
        with task_manager.acquire(self.context, info['uuid'],
                                  shared=False) as task:
            self.assertRaises(exception.InvalidParameterValue,
                              task.driver.vendor.vendor_passthru, task,
                              **{'method': 'attach_volume'})

    @mock.patch.object(seamicro, '_get_server')
    def test_set_boot_device_good(self, mock_get_server):
        info = seamicro._parse_driver_info(self.node)
        boot_device = "disk"
        mock_get_server.return_value = self.Server(active="true")
        with task_manager.acquire(self.context, info['uuid'],
                                  shared=False) as task:
            task.driver.management.set_boot_device(task, boot_device)
        mock_get_server.assert_called_once_with(info)

    @mock.patch.object(seamicro, '_get_server')
    def test_set_boot_device_invalid_device_fail(self, mock_get_server):
        info = seamicro._parse_driver_info(self.node)
        boot_device = "invalid_device"
        mock_get_server.return_value = self.Server(active="true")
        with task_manager.acquire(self.context, info['uuid'],
                                  shared=False) as task:
            self.assertRaises(exception.InvalidParameterValue,
                              task.driver.management.set_boot_device,
                              task, boot_device)

    @mock.patch.object(seamicro, '_get_server')
    def test_set_boot_device_fail(self, mock_get_server):
        def fake_set_boot_order(self, **kwargs):
            raise seamicro_client_exception.ClientException(500)

        info = seamicro._parse_driver_info(self.node)
        boot_device = "pxe"
        server = self.Server(active="true")
        server.set_boot_order = fake_set_boot_order
        mock_get_server.return_value = server
        with task_manager.acquire(self.context, info['uuid'],
                                  shared=False) as task:
            self.assertRaises(exception.IronicException,
                              task.driver.management.set_boot_device,
                              task, boot_device)

        mock_get_server.assert_called_once_with(info)

    def test_management_interface_get_supported_boot_devices(self):
        with task_manager.acquire(self.context, self.node.uuid) as task:
            expected = [boot_devices.PXE, boot_devices.DISK]
            self.assertEqual(sorted(expected), sorted(task.driver.management.
                             get_supported_boot_devices()))

    def test_management_interface_get_boot_device(self):
        with task_manager.acquire(self.context, self.node.uuid) as task:
            expected = {'boot_device': None, 'persistent': None}
            self.assertEqual(expected,
                             task.driver.management.get_boot_device(task))

    def test_management_interface_validate_good(self):
        with task_manager.acquire(self.context, self.node.uuid) as task:
            task.driver.management.validate(task)

    def test_management_interface_validate_fail(self):
        # Missing SEAMICRO driver_info information
        node = obj_utils.create_test_node(self.context, id=2,
                                          uuid=utils.generate_uuid(),
                                          driver='fake_seamicro')
        with task_manager.acquire(self.context, node.uuid) as task:
            self.assertRaises(exception.MissingParameterValue,
                              task.driver.management.validate, task)
