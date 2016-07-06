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
from oslo_utils import uuidutils
from seamicroclient import client as seamicro_client
from seamicroclient import exceptions as seamicro_client_exception
from six.moves import http_client

from ironic.common import boot_devices
from ironic.common import driver_factory
from ironic.common import exception
from ironic.common import states
from ironic.conductor import task_manager
from ironic.drivers.modules import console_utils
from ironic.drivers.modules import seamicro
from ironic.tests.unit.conductor import mgr_utils
from ironic.tests.unit.db import base as db_base
from ironic.tests.unit.db import utils as db_utils
from ironic.tests.unit.objects import utils as obj_utils

INFO_DICT = db_utils.get_test_seamicro_info()


class Fake_Server(object):
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


class Fake_Volume(object):
    def __init__(self, id=None, *args, **kwargs):
        if id is None:
            self.id = "%s/%s/%s" % ("0", "ironic-p6-6", str(uuid.uuid4()))
        else:
            self.id = id


class Fake_Pool(object):
    def __init__(self, freeSize=None, *args, **kwargs):
        self.freeSize = freeSize


class SeaMicroValidateParametersTestCase(db_base.DbTestCase):

    def test__parse_driver_info_good(self):
        # make sure we get back the expected things
        node = obj_utils.get_test_node(
            self.context,
            driver='fake_seamicro',
            driver_info=INFO_DICT)
        info = seamicro._parse_driver_info(node)
        self.assertEqual('http://1.2.3.4', info['api_endpoint'])
        self.assertEqual('admin', info['username'])
        self.assertEqual('fake', info['password'])
        self.assertEqual('0/0', info['server_id'])
        self.assertEqual('1be26c0b-03f2-4d2e-ae87-c02d7f33c123',
                         info['uuid'])

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

    def test__parse_driver_info_empty_terminal_port(self):
        info = dict(INFO_DICT)
        info['seamicro_terminal_port'] = ''
        node = obj_utils.get_test_node(self.context, driver_info=info)
        self.assertRaises(exception.InvalidParameterValue,
                          seamicro._parse_driver_info,
                          node)


@mock.patch('eventlet.greenthread.sleep', lambda n: None)
class SeaMicroPrivateMethodsTestCase(db_base.DbTestCase):

    def setUp(self):
        super(SeaMicroPrivateMethodsTestCase, self).setUp()
        n = {
            'driver': 'fake_seamicro',
            'driver_info': INFO_DICT
        }
        self.node = obj_utils.create_test_node(self.context, **n)
        self.Server = Fake_Server
        self.Volume = Fake_Volume
        self.Pool = Fake_Pool
        self.config(action_timeout=0, group='seamicro')
        self.config(max_retry=2, group='seamicro')

        self.info = seamicro._parse_driver_info(self.node)

    @mock.patch.object(seamicro_client, "Client", autospec=True)
    def test__get_client(self, mock_client):
        args = {'username': self.info['username'],
                'password': self.info['password'],
                'auth_url': self.info['api_endpoint']}
        seamicro._get_client(**self.info)
        mock_client.assert_called_once_with(self.info['api_version'], **args)

    @mock.patch.object(seamicro_client, "Client", autospec=True)
    def test__get_client_fail(self, mock_client):
        args = {'username': self.info['username'],
                'password': self.info['password'],
                'auth_url': self.info['api_endpoint']}
        mock_client.side_effect = seamicro_client_exception.UnsupportedVersion
        self.assertRaises(exception.InvalidParameterValue,
                          seamicro._get_client,
                          **self.info)
        mock_client.assert_called_once_with(self.info['api_version'], **args)

    @mock.patch.object(seamicro, "_get_server", autospec=True)
    def test__get_power_status_on(self, mock_get_server):
        mock_get_server.return_value = self.Server(active=True)
        pstate = seamicro._get_power_status(self.node)
        self.assertEqual(states.POWER_ON, pstate)

    @mock.patch.object(seamicro, "_get_server", autospec=True)
    def test__get_power_status_off(self, mock_get_server):
        mock_get_server.return_value = self.Server(active=False)
        pstate = seamicro._get_power_status(self.node)
        self.assertEqual(states.POWER_OFF, pstate)

    @mock.patch.object(seamicro, "_get_server", autospec=True)
    def test__get_power_status_error(self, mock_get_server):
        mock_get_server.return_value = self.Server(active=None)
        pstate = seamicro._get_power_status(self.node)
        self.assertEqual(states.ERROR, pstate)

    @mock.patch.object(seamicro, "_get_server", autospec=True)
    def test__power_on_good(self, mock_get_server):
        mock_get_server.return_value = self.Server(active=False)
        pstate = seamicro._power_on(self.node)
        self.assertEqual(states.POWER_ON, pstate)

    @mock.patch.object(seamicro, "_get_server", autospec=True)
    def test__power_on_fail(self, mock_get_server):
        def fake_power_on():
            return

        server = self.Server(active=False)
        server.power_on = fake_power_on
        mock_get_server.return_value = server
        pstate = seamicro._power_on(self.node)
        self.assertEqual(states.ERROR, pstate)

    @mock.patch.object(seamicro, "_get_server", autospec=True)
    def test__power_off_good(self, mock_get_server):
        mock_get_server.return_value = self.Server(active=True)
        pstate = seamicro._power_off(self.node)
        self.assertEqual(states.POWER_OFF, pstate)

    @mock.patch.object(seamicro, "_get_server", autospec=True)
    def test__power_off_fail(self, mock_get_server):
        def fake_power_off():
            return
        server = self.Server(active=True)
        server.power_off = fake_power_off
        mock_get_server.return_value = server
        pstate = seamicro._power_off(self.node)
        self.assertEqual(states.ERROR, pstate)

    @mock.patch.object(seamicro, "_get_server", autospec=True)
    def test__reboot_good(self, mock_get_server):
        mock_get_server.return_value = self.Server(active=True)
        pstate = seamicro._reboot(self.node)
        self.assertEqual(states.POWER_ON, pstate)

    @mock.patch.object(seamicro, "_get_server", autospec=True)
    def test__reboot_fail(self, mock_get_server):
        def fake_reboot():
            return
        server = self.Server(active=False)
        server.reset = fake_reboot
        mock_get_server.return_value = server
        pstate = seamicro._reboot(self.node)
        self.assertEqual(states.ERROR, pstate)

    @mock.patch.object(seamicro, "_get_volume", autospec=True)
    def test__validate_fail(self, mock_get_volume):
        volume_id = "0/p6-6/vol1"
        volume = self.Volume()
        volume.id = volume_id
        mock_get_volume.return_value = volume
        self.assertRaises(exception.InvalidParameterValue,
                          seamicro._validate_volume, self.info, volume_id)

    @mock.patch.object(seamicro, "_get_volume", autospec=True)
    def test__validate_good(self, mock_get_volume):
        volume = self.Volume()
        mock_get_volume.return_value = volume
        valid = seamicro._validate_volume(self.info, volume.id)
        self.assertTrue(valid)

    @mock.patch.object(seamicro, "_get_pools", autospec=True)
    def test__create_volume_fail(self, mock_get_pools):
        mock_get_pools.return_value = None
        self.assertRaises(exception.IronicException,
                          seamicro._create_volume,
                          self.info, 2)

    @mock.patch.object(seamicro, "_get_pools", autospec=True)
    @mock.patch.object(seamicro, "_get_client", autospec=True)
    def test__create_volume_good(self, mock_get_client, mock_get_pools):
        pools = [self.Pool(1), self.Pool(6), self.Pool(5)]
        mock_seamicro_volumes = mock.MagicMock(spec_set=['create'])
        mock_get_client.return_value = mock.MagicMock(
            volumes=mock_seamicro_volumes, spec_set=['volumes'])
        mock_get_pools.return_value = pools
        seamicro._create_volume(self.info, 2)


class SeaMicroPowerDriverTestCase(db_base.DbTestCase):

    def setUp(self):
        super(SeaMicroPowerDriverTestCase, self).setUp()
        mgr_utils.mock_the_extension_manager(driver='fake_seamicro')
        self.driver = driver_factory.get_driver('fake_seamicro')
        self.node = obj_utils.create_test_node(self.context,
                                               driver='fake_seamicro',
                                               driver_info=INFO_DICT)
        self.get_server_patcher = mock.patch.object(seamicro, '_get_server',
                                                    autospec=True)

        self.get_server_mock = None
        self.Server = Fake_Server
        self.Volume = Fake_Volume
        self.info = seamicro._parse_driver_info(self.node)

    def test_get_properties(self):
        expected = seamicro.COMMON_PROPERTIES
        with task_manager.acquire(self.context, self.node['uuid'],
                                  shared=True) as task:
            self.assertEqual(expected, task.driver.power.get_properties())

            expected = (list(seamicro.COMMON_PROPERTIES) +
                        list(seamicro.CONSOLE_PROPERTIES))
            console_properties = task.driver.console.get_properties().keys()
            self.assertEqual(sorted(expected), sorted(console_properties))
            self.assertEqual(sorted(expected),
                             sorted(task.driver.get_properties().keys()))

    def test_vendor_routes(self):
        expected = ['set_node_vlan_id', 'attach_volume']
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            vendor_routes = task.driver.vendor.vendor_routes
            self.assertIsInstance(vendor_routes, dict)
            self.assertEqual(sorted(expected), sorted(vendor_routes))

    def test_driver_routes(self):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            driver_routes = task.driver.vendor.driver_routes
            self.assertIsInstance(driver_routes, dict)
            self.assertEqual({}, driver_routes)

    @mock.patch.object(seamicro, '_parse_driver_info', autospec=True)
    def test_power_interface_validate_good(self, parse_drv_info_mock):
        with task_manager.acquire(self.context, self.node['uuid'],
                                  shared=True) as task:
            task.driver.power.validate(task)
        self.assertEqual(1, parse_drv_info_mock.call_count)

    @mock.patch.object(seamicro, '_parse_driver_info', autospec=True)
    def test_power_interface_validate_fails(self, parse_drv_info_mock):
        side_effect = exception.InvalidParameterValue("Bad input")
        parse_drv_info_mock.side_effect = side_effect
        with task_manager.acquire(self.context, self.node['uuid'],
                                  shared=True) as task:
            self.assertRaises(exception.InvalidParameterValue,
                              task.driver.power.validate, task)
        self.assertEqual(1, parse_drv_info_mock.call_count)

    @mock.patch.object(seamicro, '_reboot', autospec=True)
    def test_reboot(self, mock_reboot):
        mock_reboot.return_value = states.POWER_ON

        with task_manager.acquire(self.context, self.info['uuid'],
                                  shared=False) as task:
            task.driver.power.reboot(task)

            mock_reboot.assert_called_once_with(task.node)

    def test_set_power_state_bad_state(self):
        self.get_server_mock = self.get_server_patcher.start()
        self.get_server_mock.return_value = self.Server()

        with task_manager.acquire(self.context, self.info['uuid'],
                                  shared=False) as task:
            self.assertRaises(exception.IronicException,
                              task.driver.power.set_power_state,
                              task, "BAD_PSTATE")
        self.get_server_patcher.stop()

    @mock.patch.object(seamicro, '_power_on', autospec=True)
    def test_set_power_state_on_good(self, mock_power_on):
        mock_power_on.return_value = states.POWER_ON

        with task_manager.acquire(self.context, self.info['uuid'],
                                  shared=False) as task:
            task.driver.power.set_power_state(task, states.POWER_ON)

            mock_power_on.assert_called_once_with(task.node)

    @mock.patch.object(seamicro, '_power_on', autospec=True)
    def test_set_power_state_on_fail(self, mock_power_on):
        mock_power_on.return_value = states.POWER_OFF

        with task_manager.acquire(self.context, self.info['uuid'],
                                  shared=False) as task:
            self.assertRaises(exception.PowerStateFailure,
                              task.driver.power.set_power_state,
                              task, states.POWER_ON)

            mock_power_on.assert_called_once_with(task.node)

    @mock.patch.object(seamicro, '_power_off', autospec=True)
    def test_set_power_state_off_good(self, mock_power_off):
        mock_power_off.return_value = states.POWER_OFF

        with task_manager.acquire(self.context, self.info['uuid'],
                                  shared=False) as task:
            task.driver.power.set_power_state(task, states.POWER_OFF)

            mock_power_off.assert_called_once_with(task.node)

    @mock.patch.object(seamicro, '_power_off', autospec=True)
    def test_set_power_state_off_fail(self, mock_power_off):
        mock_power_off.return_value = states.POWER_ON

        with task_manager.acquire(self.context, self.info['uuid'],
                                  shared=False) as task:
            self.assertRaises(exception.PowerStateFailure,
                              task.driver.power.set_power_state,
                              task, states.POWER_OFF)

            mock_power_off.assert_called_once_with(task.node)

    @mock.patch.object(seamicro, '_parse_driver_info', autospec=True)
    def test_vendor_passthru_validate_good(self, mock_info):
        with task_manager.acquire(self.context, self.node['uuid'],
                                  shared=True) as task:
            for method in task.driver.vendor.vendor_routes:
                task.driver.vendor.validate(task, **{'method': method})
            self.assertEqual(len(task.driver.vendor.vendor_routes),
                             mock_info.call_count)

    @mock.patch.object(seamicro, '_parse_driver_info', autospec=True)
    def test_vendor_passthru_validate_parse_driver_info_fail(self, mock_info):
        mock_info.side_effect = exception.InvalidParameterValue("bad")
        with task_manager.acquire(self.context, self.node['uuid'],
                                  shared=True) as task:
            method = list(task.driver.vendor.vendor_routes)[0]
            self.assertRaises(exception.InvalidParameterValue,
                              task.driver.vendor.validate,
                              task, **{'method': method})
            mock_info.assert_called_once_with(task.node)

    @mock.patch.object(seamicro, '_get_server', autospec=True)
    def test_set_node_vlan_id_good(self, mock_get_server):
        vlan_id = "12"
        mock_get_server.return_value = self.Server(active="true")
        with task_manager.acquire(self.context, self.info['uuid'],
                                  shared=False) as task:
            kwargs = {'vlan_id': vlan_id}
            task.driver.vendor.set_node_vlan_id(task, **kwargs)
        mock_get_server.assert_called_once_with(self.info)

    def test_set_node_vlan_id_no_input(self):
        with task_manager.acquire(self.context, self.info['uuid'],
                                  shared=False) as task:
            self.assertRaises(exception.InvalidParameterValue,
                              task.driver.vendor.set_node_vlan_id,
                              task, **{})

    @mock.patch.object(seamicro, '_get_server', autospec=True)
    def test_set_node_vlan_id_fail(self, mock_get_server):
        def fake_set_untagged_vlan(self, **kwargs):
            raise seamicro_client_exception.ClientException(
                http_client.INTERNAL_SERVER_ERROR)

        vlan_id = "12"
        server = self.Server(active="true")
        server.set_untagged_vlan = fake_set_untagged_vlan
        mock_get_server.return_value = server
        with task_manager.acquire(self.context, self.info['uuid'],
                                  shared=False) as task:
            kwargs = {'vlan_id': vlan_id}
            self.assertRaises(exception.IronicException,
                              task.driver.vendor.set_node_vlan_id,
                              task, **kwargs)

        mock_get_server.assert_called_once_with(self.info)

    @mock.patch.object(seamicro, '_get_server', autospec=True)
    @mock.patch.object(seamicro, '_validate_volume', autospec=True)
    def test_attach_volume_with_volume_id_good(self, mock_validate_volume,
                                               mock_get_server):
        volume_id = '0/ironic-p6-1/vol1'
        mock_validate_volume.return_value = True
        mock_get_server.return_value = self.Server(active="true")
        with task_manager.acquire(self.context, self.info['uuid'],
                                  shared=False) as task:
            kwargs = {'volume_id': volume_id}
            task.driver.vendor.attach_volume(task, **kwargs)
        mock_get_server.assert_called_once_with(self.info)

    @mock.patch.object(seamicro, '_get_server', autospec=True)
    @mock.patch.object(seamicro, '_get_volume', autospec=True)
    def test_attach_volume_with_invalid_volume_id_fail(self,
                                                       mock_get_volume,
                                                       mock_get_server):
        volume_id = '0/p6-1/vol1'
        mock_get_volume.return_value = self.Volume(volume_id)
        mock_get_server.return_value = self.Server(active="true")
        with task_manager.acquire(self.context, self.info['uuid'],
                                  shared=False) as task:
            kwargs = {'volume_id': volume_id}
            self.assertRaises(exception.InvalidParameterValue,
                              task.driver.vendor.attach_volume,
                              task, **kwargs)

    @mock.patch.object(seamicro, '_get_server', autospec=True)
    @mock.patch.object(seamicro, '_validate_volume', autospec=True)
    def test_attach_volume_fail(self, mock_validate_volume,
                                mock_get_server):
        def fake_attach_volume(self, **kwargs):
            raise seamicro_client_exception.ClientException(
                http_client.INTERNAL_SERVER_ERROR)

        volume_id = '0/p6-1/vol1'
        mock_validate_volume.return_value = True
        server = self.Server(active="true")
        server.attach_volume = fake_attach_volume
        mock_get_server.return_value = server
        with task_manager.acquire(self.context, self.info['uuid'],
                                  shared=False) as task:
            kwargs = {'volume_id': volume_id}
            self.assertRaises(exception.IronicException,
                              task.driver.vendor.attach_volume,
                              task, **kwargs)

        mock_get_server.assert_called_once_with(self.info)

    @mock.patch.object(seamicro, '_get_server', autospec=True)
    @mock.patch.object(seamicro, '_validate_volume', autospec=True)
    @mock.patch.object(seamicro, '_create_volume', autospec=True)
    def test_attach_volume_with_volume_size_good(self, mock_create_volume,
                                                 mock_validate_volume,
                                                 mock_get_server):
        volume_id = '0/ironic-p6-1/vol1'
        volume_size = 2
        mock_create_volume.return_value = volume_id
        mock_validate_volume.return_value = True
        mock_get_server.return_value = self.Server(active="true")
        with task_manager.acquire(self.context, self.info['uuid'],
                                  shared=False) as task:
            kwargs = {'volume_size': volume_size}
            task.driver.vendor.attach_volume(task, **kwargs)
        mock_get_server.assert_called_once_with(self.info)
        mock_create_volume.assert_called_once_with(self.info, volume_size)

    def test_attach_volume_with_no_input_fail(self):
        with task_manager.acquire(self.context, self.info['uuid'],
                                  shared=False) as task:
            self.assertRaises(exception.InvalidParameterValue,
                              task.driver.vendor.attach_volume, task,
                              **{})

    @mock.patch.object(seamicro, '_get_server', autospec=True)
    def test_set_boot_device_good(self, mock_get_server):
        boot_device = "disk"
        mock_get_server.return_value = self.Server(active="true")
        with task_manager.acquire(self.context, self.info['uuid'],
                                  shared=False) as task:
            task.driver.management.set_boot_device(task, boot_device)
        mock_get_server.assert_called_once_with(self.info)

    @mock.patch.object(seamicro, '_get_server', autospec=True)
    def test_set_boot_device_invalid_device_fail(self, mock_get_server):
        boot_device = "invalid_device"
        mock_get_server.return_value = self.Server(active="true")
        with task_manager.acquire(self.context, self.info['uuid'],
                                  shared=False) as task:
            self.assertRaises(exception.InvalidParameterValue,
                              task.driver.management.set_boot_device,
                              task, boot_device)

    @mock.patch.object(seamicro, '_get_server', autospec=True)
    def test_set_boot_device_fail(self, mock_get_server):
        def fake_set_boot_order(self, **kwargs):
            raise seamicro_client_exception.ClientException(
                http_client.INTERNAL_SERVER_ERROR)

        boot_device = "pxe"
        server = self.Server(active="true")
        server.set_boot_order = fake_set_boot_order
        mock_get_server.return_value = server
        with task_manager.acquire(self.context, self.info['uuid'],
                                  shared=False) as task:
            self.assertRaises(exception.IronicException,
                              task.driver.management.set_boot_device,
                              task, boot_device)

        mock_get_server.assert_called_once_with(self.info)

    def test_management_interface_get_supported_boot_devices(self):
        with task_manager.acquire(self.context, self.node.uuid) as task:
            expected = [boot_devices.PXE, boot_devices.DISK]
            self.assertEqual(sorted(expected), sorted(task.driver.management.
                             get_supported_boot_devices(task)))

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
        node = obj_utils.create_test_node(self.context,
                                          uuid=uuidutils.generate_uuid(),
                                          driver='fake_seamicro')
        with task_manager.acquire(self.context, node.uuid) as task:
            self.assertRaises(exception.MissingParameterValue,
                              task.driver.management.validate, task)


class SeaMicroDriverTestCase(db_base.DbTestCase):

    def setUp(self):
        super(SeaMicroDriverTestCase, self).setUp()
        mgr_utils.mock_the_extension_manager(driver='fake_seamicro')
        self.driver = driver_factory.get_driver('fake_seamicro')
        self.node = obj_utils.create_test_node(self.context,
                                               driver='fake_seamicro',
                                               driver_info=INFO_DICT)
        self.get_server_patcher = mock.patch.object(seamicro, '_get_server',
                                                    autospec=True)

        self.get_server_mock = None
        self.Server = Fake_Server
        self.Volume = Fake_Volume
        self.info = seamicro._parse_driver_info(self.node)

    @mock.patch.object(console_utils, 'start_shellinabox_console',
                       autospec=True)
    def test_start_console(self, mock_exec):
        mock_exec.return_value = None
        with task_manager.acquire(self.context,
                                  self.node.uuid) as task:
            self.driver.console.start_console(task)

        mock_exec.assert_called_once_with(self.info['uuid'],
                                          self.info['port'],
                                          mock.ANY)

    @mock.patch.object(console_utils, 'start_shellinabox_console',
                       autospec=True)
    def test_start_console_fail(self, mock_exec):
        mock_exec.side_effect = exception.ConsoleSubprocessFailed(
            error='error')

        with task_manager.acquire(self.context,
                                  self.node.uuid) as task:
            self.assertRaises(exception.ConsoleSubprocessFailed,
                              self.driver.console.start_console,
                              task)

    @mock.patch.object(console_utils, 'stop_shellinabox_console',
                       autospec=True)
    def test_stop_console(self, mock_exec):
        mock_exec.return_value = None
        with task_manager.acquire(self.context,
                                  self.node.uuid) as task:
            self.driver.console.stop_console(task)

        mock_exec.assert_called_once_with(self.info['uuid'])

    @mock.patch.object(console_utils, 'stop_shellinabox_console',
                       autospec=True)
    def test_stop_console_fail(self, mock_stop):
        mock_stop.side_effect = exception.ConsoleError()

        with task_manager.acquire(self.context,
                                  self.node.uuid) as task:
            self.assertRaises(exception.ConsoleError,
                              self.driver.console.stop_console,
                              task)

        mock_stop.assert_called_once_with(self.node.uuid)

    @mock.patch.object(console_utils, 'start_shellinabox_console',
                       autospec=True)
    def test_start_console_fail_nodir(self, mock_exec):
        mock_exec.side_effect = exception.ConsoleError()

        with task_manager.acquire(self.context,
                                  self.node.uuid) as task:
            self.assertRaises(exception.ConsoleError,
                              self.driver.console.start_console,
                              task)
        mock_exec.assert_called_once_with(self.node.uuid, mock.ANY, mock.ANY)

    @mock.patch.object(console_utils, 'get_shellinabox_console_url',
                       autospec=True)
    def test_get_console(self, mock_exec):
        url = 'http://localhost:4201'
        mock_exec.return_value = url
        expected = {'type': 'shellinabox', 'url': url}

        with task_manager.acquire(self.context,
                                  self.node.uuid) as task:
            console_info = self.driver.console.get_console(task)

        self.assertEqual(expected, console_info)
        mock_exec.assert_called_once_with(self.info['port'])
