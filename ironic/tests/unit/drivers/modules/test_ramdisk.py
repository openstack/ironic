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

"""Test class for ramdisk deploy."""

import tempfile
from unittest import mock

from oslo_config import cfg

from ironic.common import boot_devices
from ironic.common import dhcp_factory
from ironic.common import exception
from ironic.common import pxe_utils
from ironic.common import states
from ironic.conductor import task_manager
from ironic.conductor import utils as manager_utils
from ironic.drivers import base as drivers_base
from ironic.drivers.modules import agent_base
from ironic.drivers.modules import deploy_utils
from ironic.drivers.modules import fake
from ironic.drivers.modules import pxe
from ironic.drivers.modules import ramdisk
from ironic.tests.unit.db import base as db_base
from ironic.tests.unit.db import utils as db_utils
from ironic.tests.unit.objects import utils as obj_utils

CONF = cfg.CONF
DRV_INFO_DICT = db_utils.get_test_pxe_driver_info()
DRV_INTERNAL_INFO_DICT = db_utils.get_test_pxe_driver_internal_info()


class RamdiskDeployTestCase(db_base.DbTestCase):

    def setUp(self):
        super(RamdiskDeployTestCase, self).setUp()
        self.temp_dir = tempfile.mkdtemp()
        self.config(tftp_root=self.temp_dir, group='pxe')
        self.temp_dir = tempfile.mkdtemp()
        self.config(images_path=self.temp_dir, group='pxe')
        for iface in drivers_base.ALL_INTERFACES:
            impl = 'fake'
            if iface == 'network':
                impl = 'noop'
            if iface == 'deploy':
                impl = 'ramdisk'
            if iface == 'boot':
                impl = 'pxe'
            config_kwarg = {'enabled_%s_interfaces' % iface: [impl],
                            'default_%s_interface' % iface: impl}
            self.config(**config_kwarg)
        self.config(enabled_hardware_types=['fake-hardware'])
        instance_info = {'kernel': 'kernelUUID',
                         'ramdisk': 'ramdiskUUID'}
        self.node = obj_utils.create_test_node(
            self.context,
            driver='fake-hardware',
            instance_info=instance_info,
            driver_info=DRV_INFO_DICT,
            driver_internal_info=DRV_INTERNAL_INFO_DICT)
        self.port = obj_utils.create_test_port(self.context,
                                               node_id=self.node.id)

    @mock.patch.object(manager_utils, 'node_set_boot_device', autospec=True)
    @mock.patch.object(deploy_utils, 'switch_pxe_config', autospec=True)
    @mock.patch.object(dhcp_factory, 'DHCPFactory', autospec=True)
    @mock.patch.object(pxe_utils, 'cache_ramdisk_kernel', autospec=True)
    @mock.patch.object(pxe_utils, 'get_instance_image_info', autospec=True)
    def test_prepare_instance_ramdisk(
            self, get_image_info_mock, cache_mock,
            dhcp_factory_mock, switch_pxe_config_mock,
            set_boot_device_mock):
        provider_mock = mock.MagicMock()
        dhcp_factory_mock.return_value = provider_mock
        self.node.provision_state = states.DEPLOYING
        image_info = {'kernel': ('', '/path/to/kernel'),
                      'ramdisk': ('', '/path/to/ramdisk')}
        get_image_info_mock.return_value = image_info
        with task_manager.acquire(self.context, self.node.uuid) as task:
            dhcp_opts = pxe_utils.dhcp_options_for_instance(
                task, ipxe_enabled=False)
            dhcp_opts += pxe_utils.dhcp_options_for_instance(
                task, ipxe_enabled=False, ip_version=6)
            pxe_config_path = pxe_utils.get_pxe_config_file_path(
                task.node.uuid)
            task.node.properties['capabilities'] = 'boot_option:netboot'
            task.node.driver_internal_info['is_whole_disk_image'] = False
            task.driver.deploy.prepare(task)
            task.driver.deploy.deploy(task)

            get_image_info_mock.assert_called_once_with(task,
                                                        ipxe_enabled=False)
            cache_mock.assert_called_once_with(
                task, image_info, ipxe_enabled=False)
            provider_mock.update_dhcp.assert_called_once_with(task, dhcp_opts)
            switch_pxe_config_mock.assert_called_once_with(
                pxe_config_path, None,
                CONF.deploy.default_boot_mode, False, ipxe_enabled=False,
                iscsi_boot=False, ramdisk_boot=True, anaconda_boot=False)
            set_boot_device_mock.assert_called_once_with(task,
                                                         boot_devices.PXE,
                                                         persistent=True)

    @mock.patch.object(ramdisk.LOG, 'warning', autospec=True)
    @mock.patch.object(deploy_utils, 'switch_pxe_config', autospec=True)
    @mock.patch.object(dhcp_factory, 'DHCPFactory', autospec=True)
    @mock.patch.object(pxe_utils, 'cache_ramdisk_kernel', autospec=True)
    @mock.patch.object(pxe_utils, 'get_instance_image_info', autospec=True)
    def test_deploy(self, mock_image_info, mock_cache,
                    mock_dhcp_factory, mock_switch_config, mock_warning):
        image_info = {'kernel': ('', '/path/to/kernel'),
                      'ramdisk': ('', '/path/to/ramdisk')}
        mock_image_info.return_value = image_info
        i_info = self.node.instance_info
        i_info.update({'capabilities': {'boot_option': 'ramdisk'}})
        self.node.instance_info = i_info
        self.node.save()
        with task_manager.acquire(self.context, self.node.uuid) as task:
            self.assertIsNone(task.driver.deploy.deploy(task))
            mock_image_info.assert_called_once_with(task, ipxe_enabled=False)
            mock_cache.assert_called_once_with(
                task, image_info, ipxe_enabled=False)
            self.assertFalse(mock_warning.called)
        i_info['configdrive'] = 'meow'
        self.node.instance_info = i_info
        self.node.save()
        mock_warning.reset_mock()
        with task_manager.acquire(self.context, self.node.uuid) as task:
            self.assertIsNone(task.driver.deploy.deploy(task))
            self.assertTrue(mock_warning.called)

    @mock.patch.object(pxe.PXEBoot, 'prepare_instance', autospec=True)
    def test_prepare(self, mock_prepare_instance):
        node = self.node
        node.provision_state = states.DEPLOYING
        node.instance_info = {}
        node.save()
        with task_manager.acquire(self.context, node.uuid) as task:
            task.driver.deploy.prepare(task)
            self.assertFalse(mock_prepare_instance.called)

    @mock.patch.object(pxe.PXEBoot, 'prepare_instance', autospec=True)
    def test_prepare_active(self, mock_prepare_instance):
        node = self.node
        node.provision_state = states.ACTIVE
        node.save()
        with task_manager.acquire(self.context, node.uuid) as task:
            task.driver.deploy.prepare(task)
            mock_prepare_instance.assert_called_once_with(mock.ANY, task)

    @mock.patch.object(pxe.PXEBoot, 'prepare_instance', autospec=True)
    def test_prepare_unrescuing(self, mock_prepare_instance):
        node = self.node
        node.provision_state = states.UNRESCUING
        node.save()
        with task_manager.acquire(self.context, node.uuid) as task:
            task.driver.deploy.prepare(task)
            mock_prepare_instance.assert_called_once_with(mock.ANY, task)

    @mock.patch.object(deploy_utils, 'validate_image_properties',
                       autospec=True)
    def test_validate(self, mock_validate_img):
        with task_manager.acquire(self.context, self.node.uuid) as task:
            task.driver.deploy.validate(task)
        self.assertTrue(mock_validate_img.called)

    @mock.patch.object(deploy_utils, 'validate_image_properties',
                       autospec=True)
    def test_validate_with_boot_iso(self, mock_validate_img):
        with task_manager.acquire(self.context, self.node.uuid) as task:
            task.node.instance_info = {
                'boot_iso': 'isoUUID'
            }
            task.driver.deploy.validate(task)
        self.assertTrue(mock_validate_img.called)

    @mock.patch.object(fake.FakeBoot, 'validate', autospec=True)
    @mock.patch.object(deploy_utils, 'validate_image_properties',
                       autospec=True)
    def test_validate_interface_mismatch(self, mock_validate_image,
                                         mock_boot_validate):
        node = self.node
        node.boot_interface = 'fake'
        node.save()
        self.config(enabled_boot_interfaces=['fake'],
                    default_boot_interface='fake')
        with task_manager.acquire(self.context, node.uuid) as task:
            error = self.assertRaises(exception.InvalidParameterValue,
                                      task.driver.deploy.validate, task)
            error_message = ('Invalid configuration: The boot interface must '
                             'have the `ramdisk_boot` capability. You are '
                             'using an incompatible boot interface.')
            self.assertEqual(error_message, str(error))
            self.assertFalse(mock_boot_validate.called)
            self.assertFalse(mock_validate_image.called)

    @mock.patch.object(pxe.PXEBoot, 'validate', autospec=True)
    def test_validate_calls_boot_validate(self, mock_validate):
        with task_manager.acquire(self.context, self.node.uuid) as task:
            task.driver.deploy.validate(task)
            mock_validate.assert_called_once_with(mock.ANY, task)

    @mock.patch.object(manager_utils, 'restore_power_state_if_needed',
                       autospec=True)
    @mock.patch.object(manager_utils, 'power_on_node_if_needed',
                       autospec=True)
    @mock.patch.object(ramdisk.LOG, 'warning', autospec=True)
    @mock.patch.object(deploy_utils, 'switch_pxe_config', autospec=True)
    @mock.patch.object(dhcp_factory, 'DHCPFactory', autospec=True)
    @mock.patch.object(pxe_utils, 'cache_ramdisk_kernel', autospec=True)
    @mock.patch.object(pxe_utils, 'get_instance_image_info', autospec=True)
    def test_deploy_with_smartnic_port(
            self, mock_image_info, mock_cache,
            mock_dhcp_factory, mock_switch_config, mock_warning,
            power_on_node_if_needed_mock, restore_power_state_mock):
        image_info = {'kernel': ('', '/path/to/kernel'),
                      'ramdisk': ('', '/path/to/ramdisk')}
        mock_image_info.return_value = image_info
        i_info = self.node.instance_info
        i_info.update({'capabilities': {'boot_option': 'ramdisk'}})
        self.node.instance_info = i_info
        self.node.save()
        with task_manager.acquire(self.context, self.node.uuid) as task:
            power_on_node_if_needed_mock.return_value = states.POWER_OFF
            self.assertIsNone(task.driver.deploy.deploy(task))
            mock_image_info.assert_called_once_with(task, ipxe_enabled=False)
            mock_cache.assert_called_once_with(
                task, image_info, ipxe_enabled=False)
            self.assertFalse(mock_warning.called)
            power_on_node_if_needed_mock.assert_called_once_with(task)
            restore_power_state_mock.assert_called_once_with(
                task, states.POWER_OFF)
        i_info['configdrive'] = 'meow'
        self.node.instance_info = i_info
        self.node.save()
        mock_warning.reset_mock()
        with task_manager.acquire(self.context, self.node.uuid) as task:
            self.assertIsNone(task.driver.deploy.deploy(task))
            self.assertTrue(mock_warning.called)

    @mock.patch.object(agent_base, 'get_steps', autospec=True)
    def test_get_clean_steps(self, mock_get_steps):
        # Test getting clean steps
        mock_steps = [{'priority': 10, 'interface': 'deploy',
                       'step': 'erase_devices'}]
        mock_get_steps.return_value = mock_steps
        with task_manager.acquire(self.context, self.node.uuid) as task:
            steps = task.driver.deploy.get_clean_steps(task)
            mock_get_steps.assert_called_once_with(
                task, 'clean', interface='deploy',
                override_priorities={'erase_devices': None,
                                     'erase_devices_metadata': None})
        self.assertEqual(mock_steps, steps)

    def test_get_deploy_steps(self):
        # Only the default deploy step exists in the ramdisk deploy
        expected = [{'argsinfo': None, 'interface': 'deploy', 'priority': 100,
                     'step': 'deploy'}]
        with task_manager.acquire(self.context, self.node.uuid) as task:
            steps = task.driver.deploy.get_deploy_steps(task)
            self.assertEqual(expected, steps)

    @mock.patch.object(agent_base, 'execute_step', autospec=True)
    def test_execute_clean_step(self, mock_execute_step):
        step = {
            'priority': 10,
            'interface': 'deploy',
            'step': 'erase_devices',
            'reboot_requested': False
        }
        with task_manager.acquire(self.context, self.node.uuid) as task:
            result = task.driver.deploy.execute_clean_step(task, step)
            self.assertIs(result, mock_execute_step.return_value)
            mock_execute_step.assert_called_once_with(task, step, 'clean')

    @mock.patch.object(deploy_utils, 'prepare_inband_cleaning', autospec=True)
    def test_prepare_cleaning(self, prepare_inband_cleaning_mock):
        prepare_inband_cleaning_mock.return_value = states.CLEANWAIT
        with task_manager.acquire(self.context, self.node.uuid) as task:
            self.assertEqual(
                states.CLEANWAIT, task.driver.deploy.prepare_cleaning(task))
            prepare_inband_cleaning_mock.assert_called_once_with(
                task, manage_boot=True)

    @mock.patch.object(deploy_utils, 'tear_down_inband_cleaning',
                       autospec=True)
    def test_tear_down_cleaning(self, tear_down_cleaning_mock):
        with task_manager.acquire(self.context, self.node.uuid) as task:
            task.driver.deploy.tear_down_cleaning(task)
            tear_down_cleaning_mock.assert_called_once_with(
                task, manage_boot=True)
