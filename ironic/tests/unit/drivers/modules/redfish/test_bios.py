# Copyright 2018 DMTF. All rights reserved.
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

from unittest import mock

from oslo_utils import importutils

from ironic.common import exception
from ironic.common import states
from ironic.conductor import task_manager
from ironic.conductor import utils as manager_utils
from ironic.drivers.modules import deploy_utils
from ironic.drivers.modules.redfish import bios as redfish_bios
from ironic.drivers.modules.redfish import boot as redfish_boot
from ironic.drivers.modules.redfish import utils as redfish_utils
from ironic import objects
from ironic.tests.unit.db import base as db_base
from ironic.tests.unit.db import utils as db_utils
from ironic.tests.unit.objects import utils as obj_utils

sushy = importutils.try_import('sushy')

INFO_DICT = db_utils.get_test_redfish_info()


class NoBiosSystem(object):
    identity = '/redfish/v1/Systems/1234'

    @property
    def bios(self):
        raise sushy.exceptions.MissingAttributeError(attribute='Bios',
                                                     resource=self)


@mock.patch('oslo_utils.eventletutils.EventletEvent.wait',
            lambda *args, **kwargs: None)
class RedfishBiosTestCase(db_base.DbTestCase):

    def setUp(self):
        super(RedfishBiosTestCase, self).setUp()
        self.config(enabled_bios_interfaces=['redfish'],
                    enabled_hardware_types=['redfish'],
                    enabled_power_interfaces=['redfish'],
                    enabled_boot_interfaces=['redfish-virtual-media'],
                    enabled_management_interfaces=['redfish'])
        self.node = obj_utils.create_test_node(
            self.context, driver='redfish', driver_info=INFO_DICT)

    @mock.patch.object(redfish_bios, 'sushy', None)
    def test_loading_error(self):
        self.assertRaisesRegex(
            exception.DriverLoadError,
            'Unable to import the sushy library',
            redfish_bios.RedfishBIOS)

    def test_get_properties(self):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            properties = task.driver.get_properties()
            for prop in redfish_utils.COMMON_PROPERTIES:
                self.assertIn(prop, properties)

    @mock.patch.object(redfish_utils, 'parse_driver_info', autospec=True)
    def test_validate(self, mock_parse_driver_info):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            task.driver.bios.validate(task)
            mock_parse_driver_info.assert_called_once_with(task.node)

    @mock.patch.object(redfish_utils, 'get_system', autospec=True)
    @mock.patch.object(objects, 'BIOSSettingList', autospec=True)
    def test_cache_bios_settings_noop(self, mock_setting_list,
                                      mock_get_system):
        create_list = []
        update_list = []
        delete_list = []
        nochange_list = [{'name': 'EmbeddedSata', 'value': 'Raid'},
                         {'name': 'NicBoot1', 'value': 'NetworkBoot'}]
        mock_setting_list.sync_node_setting.return_value = (
            create_list, update_list, delete_list, nochange_list
        )

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            settings = {'foo': 'bar'}
            mock_get_system.return_value.bios.attributes = settings

            task.driver.bios.cache_bios_settings(task)
            mock_get_system.assert_called_once_with(task.node)
            mock_setting_list.sync_node_setting.assert_called_once_with(
                task.context, task.node.id,
                [{'name': 'foo', 'value': 'bar'}])

            mock_setting_list.create.assert_not_called()
            mock_setting_list.save.assert_not_called()
            mock_setting_list.delete.assert_not_called()

    @mock.patch.object(redfish_utils, 'get_system', autospec=True)
    @mock.patch.object(objects, 'BIOSSettingList', autospec=True)
    def test_cache_bios_settings_no_bios(self, mock_setting_list,
                                         mock_get_system):
        create_list = []
        update_list = []
        delete_list = []
        nochange_list = [{'name': 'EmbeddedSata', 'value': 'Raid'},
                         {'name': 'NicBoot1', 'value': 'NetworkBoot'}]
        mock_setting_list.sync_node_setting.return_value = (
            create_list, update_list, delete_list, nochange_list
        )
        mock_get_system.return_value = NoBiosSystem()

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            self.assertRaisesRegex(exception.UnsupportedDriverExtension,
                                   'BIOS settings are not supported',
                                   task.driver.bios.cache_bios_settings, task)
            mock_get_system.assert_called_once_with(task.node)
            mock_setting_list.sync_node_setting.assert_not_called()
            mock_setting_list.create.assert_not_called()
            mock_setting_list.save.assert_not_called()
            mock_setting_list.delete.assert_not_called()

    @mock.patch.object(redfish_utils, 'get_system', autospec=True)
    @mock.patch.object(objects, 'BIOSSettingList', autospec=True)
    def test_cache_bios_settings(self, mock_setting_list, mock_get_system):
        create_list = [{'name': 'DebugMode', 'value': 'enabled'}]
        update_list = [{'name': 'BootMode', 'value': 'Uefi'},
                       {'name': 'NicBoot2', 'value': 'NetworkBoot'}]
        delete_list = [{'name': 'AdminPhone', 'value': '555-867-5309'}]
        nochange_list = [{'name': 'EmbeddedSata', 'value': 'Raid'},
                         {'name': 'NicBoot1', 'value': 'NetworkBoot'}]
        delete_names = []
        for setting in delete_list:
            delete_names.append(setting.get('name'))
        mock_setting_list.sync_node_setting.return_value = (
            create_list, update_list, delete_list, nochange_list
        )

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            settings = {'foo': 'bar'}
            mock_get_system.return_value.bios.attributes = settings

            task.driver.bios.cache_bios_settings(task)
            mock_get_system.assert_called_once_with(task.node)
            mock_setting_list.sync_node_setting.assert_called_once_with(
                task.context, task.node.id,
                [{'name': 'foo', 'value': 'bar'}])

            mock_setting_list.create.assert_called_once_with(
                task.context, task.node.id, create_list)
            mock_setting_list.save.assert_called_once_with(
                task.context, task.node.id, update_list)
            mock_setting_list.delete.assert_called_once_with(
                task.context, task.node.id, delete_names)

    @mock.patch.object(manager_utils, 'is_fast_track', autospec=True)
    @mock.patch.object(redfish_boot.RedfishVirtualMediaBoot, 'prepare_ramdisk',
                       spec_set=True, autospec=True)
    @mock.patch.object(deploy_utils, 'build_agent_options', autospec=True)
    @mock.patch.object(redfish_utils, 'get_system', autospec=True)
    @mock.patch.object(manager_utils, 'node_power_action', autospec=True)
    def _test_step_pre_reboot(self, mock_power_action, mock_get_system,
                              mock_build_agent_options, mock_prepare,
                              mock_fast_track, fast_track=False):
        mock_fast_track.return_value = fast_track
        if self.node.clean_step:
            step_data = self.node.clean_step
            check_fields = ['cleaning_reboot', 'skip_current_clean_step']
            expected_ret = states.CLEANWAIT
        else:
            step_data = self.node.deploy_step
            check_fields = ['deployment_reboot', 'skip_current_deploy_step']
            expected_ret = states.DEPLOYWAIT
        data = step_data['argsinfo'].get('settings', None)
        step = step_data['step']
        if step == 'factory_reset':
            check_fields.append('post_factory_reset_reboot_requested')
        elif step == 'apply_configuration':
            check_fields.append('post_config_reboot_requested')
            attributes = {s['name']: s['value'] for s in data}
        mock_build_agent_options.return_value = {'a': 'b'}
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            bios = mock_get_system(task.node).bios
            if step == 'factory_reset':
                ret = task.driver.bios.factory_reset(task)
            if step == 'apply_configuration':
                bios.supported_apply_times = []
                ret = task.driver.bios.apply_configuration(task, data)
            mock_get_system.assert_called_with(task.node)
            if fast_track:
                mock_power_action.assert_has_calls([
                    mock.call(task, states.POWER_OFF),
                    mock.call(task, states.REBOOT),
                ])
            else:
                mock_power_action.assert_called_once_with(task, states.REBOOT)
            if step == 'factory_reset':
                bios.reset_bios.assert_called_once()
            if step == 'apply_configuration':
                bios.set_attributes.assert_called_once_with(
                    attributes, apply_time=None)
            mock_build_agent_options.assert_called_once_with(task.node)
            mock_prepare.assert_called_once_with(mock.ANY, task, {'a': 'b'})
            for field in check_fields:
                self.assertIn(field, task.node.driver_internal_info)
            self.assertEqual(expected_ret, ret)

    def test_factory_reset_step_pre_reboot_cleaning(self):
        self.node.clean_step = {'priority': 100, 'interface': 'bios',
                                'step': 'factory_reset', 'argsinfo': {}}
        self.node.save()
        self._test_step_pre_reboot()

    def test_factory_reset_step_pre_reboot_deploying(self):
        self.node.deploy_step = {'priority': 100, 'interface': 'bios',
                                 'step': 'factory_reset', 'argsinfo': {}}
        self.node.save()
        self._test_step_pre_reboot()

    def test_factory_reset_step_pre_reboot_fast_track(self):
        self.node.clean_step = {'priority': 100, 'interface': 'bios',
                                'step': 'factory_reset', 'argsinfo': {}}
        self.node.save()
        self._test_step_pre_reboot(fast_track=True)

    def test_apply_conf_step_pre_reboot_cleaning(self):
        data = [{'name': 'ProcTurboMode', 'value': 'Disabled'},
                {'name': 'NicBoot1', 'value': 'NetworkBoot'}]
        self.node.clean_step = {'priority': 100, 'interface': 'bios',
                                'step': 'apply_configuration',
                                'argsinfo': {'settings': data}}
        self.node.save()
        self._test_step_pre_reboot()

    def test_apply_conf_step_pre_reboot_deploying(self):
        data = [{'name': 'ProcTurboMode', 'value': 'Disabled'},
                {'name': 'NicBoot1', 'value': 'NetworkBoot'}]
        self.node.deploy_step = {'priority': 100, 'interface': 'bios',
                                 'step': 'apply_configuration',
                                 'argsinfo': {'settings': data}}
        self.node.save()
        self._test_step_pre_reboot()

    def test_apply_conf_step_pre_reboot_fast_track(self):
        data = [{'name': 'ProcTurboMode', 'value': 'Disabled'},
                {'name': 'NicBoot1', 'value': 'NetworkBoot'}]
        self.node.clean_step = {'priority': 100, 'interface': 'bios',
                                'step': 'apply_configuration',
                                'argsinfo': {'settings': data}}
        self.node.save()
        self._test_step_pre_reboot(fast_track=True)

    @mock.patch.object(redfish_utils, 'get_system', autospec=True)
    def _test_step_post_reboot(self, mock_get_system,
                               attributes_after_reboot=None):
        if self.node.deploy_step:
            step_data = self.node.deploy_step
        else:
            step_data = self.node.clean_step
        data = step_data['argsinfo'].get('settings', None)
        step = step_data['step']
        if step == 'factory_reset':
            check_fields = ['post_factory_reset_reboot_requested']
        if step == 'apply_configuration':
            mock_bios = mock.Mock()
            # if attributes after reboot not provided then mimic success
            # by returning the same as requested
            mock_bios.attributes = attributes_after_reboot \
                or self.node.driver_internal_info['requested_bios_attrs']
            mock_bios.get_attribute_registry = []
            mock_system = mock.Mock()
            mock_system.bios = mock_bios
            mock_get_system.return_value = mock_system
            check_fields = ['post_config_reboot_requested',
                            'requested_bios_attrs']
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            if step == 'factory_reset':
                task.driver.bios.factory_reset(task)
            if step == 'apply_configuration':
                task.driver.bios.apply_configuration(task, data)
            mock_get_system.assert_called_with(task.node)
            info = task.node.driver_internal_info
            for field in check_fields:
                self.assertNotIn(field, info)

    def test_factory_reset_post_reboot_cleaning(self):
        self.node.clean_step = {'priority': 100, 'interface': 'bios',
                                'step': 'factory_reset', 'argsinfo': {}}
        node = self.node
        driver_internal_info = node.driver_internal_info
        driver_internal_info['post_factory_reset_reboot_requested'] = True
        node.driver_internal_info = driver_internal_info
        node.save()
        self._test_step_post_reboot()

    def test_factory_reset_post_reboot_deploying(self):
        self.node.deploy_step = {'priority': 100, 'interface': 'bios',
                                 'step': 'factory_reset', 'argsinfo': {}}
        node = self.node
        driver_internal_info = node.driver_internal_info
        driver_internal_info['post_factory_reset_reboot_requested'] = True
        node.driver_internal_info = driver_internal_info
        node.save()
        self._test_step_post_reboot()

    @mock.patch.object(manager_utils, 'cleaning_error_handler', autospec=True)
    @mock.patch.object(manager_utils, 'deploying_error_handler', autospec=True)
    def test_apply_conf_post_reboot_cleaning(self,
                                             mock_deploying_error_handler,
                                             mock_cleaning_error_handler):
        data = [{'name': 'ProcTurboMode', 'value': 'Enabled'},
                {'name': 'NicBoot1', 'value': 'NetworkBoot'}]
        self.node.clean_step = {'priority': 100, 'interface': 'bios',
                                'step': 'apply_configuration',
                                'argsinfo': {'settings': data}}
        requested_attrs = {'ProcTurboMode': 'Enabled',
                           'NicBoot1': 'NetworkBoot'}
        node = self.node
        driver_internal_info = node.driver_internal_info
        driver_internal_info['post_config_reboot_requested'] = True
        driver_internal_info['requested_bios_attrs'] = requested_attrs
        self.node.driver_internal_info = driver_internal_info
        self.node.save()
        self._test_step_post_reboot()
        mock_cleaning_error_handler.assert_not_called()
        mock_deploying_error_handler.assert_not_called()

    @mock.patch.object(manager_utils, 'cleaning_error_handler', autospec=True)
    def test_apply_conf_post_reboot_cleaning_failed(
            self, mock_cleaning_error_handler):
        data = [{'name': 'ProcTurboMode', 'value': 'Enabled',
                 'registry': {'description': 'Turbo mode'}}]
        self.node.clean_step = {'priority': 100, 'interface': 'bios',
                                'step': 'apply_configuration',
                                'argsinfo': {'settings': data}}
        requested_attrs = {'ProcTurboMode': 'Enabled'}
        attributes_after_reboot = {'ProcTurboMode': 'Disabled'}
        node = self.node
        driver_internal_info = node.driver_internal_info
        driver_internal_info['post_config_reboot_requested'] = True
        driver_internal_info['requested_bios_attrs'] = requested_attrs
        self.node.driver_internal_info = driver_internal_info
        self.node.provision_state = states.CLEANING
        self.node.save()
        self._test_step_post_reboot(
            attributes_after_reboot=attributes_after_reboot)
        mock_cleaning_error_handler.assert_called_once()

    def test_apply_conf_post_reboot_deploying(self):
        data = [{'name': 'ProcTurboMode', 'value': 'Enabled',
                 'registry': {'description': 'Turbo mode'}},
                {'name': 'NicBoot1', 'value': 'NetworkBoot',
                 'registry': {'description': 'Boot off network'}}]
        self.node.deploy_step = {'priority': 100, 'interface': 'bios',
                                 'step': 'apply_configuration',
                                 'argsinfo': {'settings': data}}
        requested_attrs = {'ProcTurboMode': 'Enabled',
                           'NicBoot1': 'NetworkBoot'}
        node = self.node
        driver_internal_info = node.driver_internal_info
        driver_internal_info['post_config_reboot_requested'] = True
        driver_internal_info['requested_bios_attrs'] = requested_attrs
        self.node.driver_internal_info = driver_internal_info
        self.node.save()
        self._test_step_post_reboot()

    @mock.patch.object(manager_utils, 'deploying_error_handler', autospec=True)
    def test_apply_conf_post_reboot_deploying_failed(
            self, mock_deploying_error_handler):
        data = [{'name': 'ProcTurboMode', 'value': 'Enabled',
                 'registry': {'description': 'Turbo mode'}}]
        self.node.deploy_step = {'priority': 100, 'interface': 'bios',
                                 'step': 'apply_configuration',
                                 'argsinfo': {'settings': data}}
        requested_attrs = {'ProcTurboMode': 'Enabled'}
        attributes_after_reboot = {'ProcTurboMode': 'Disabled'}
        node = self.node
        driver_internal_info = node.driver_internal_info
        driver_internal_info['post_config_reboot_requested'] = True
        driver_internal_info['requested_bios_attrs'] = requested_attrs
        self.node.driver_internal_info = driver_internal_info
        self.node.provision_state = states.DEPLOYWAIT
        self.node.save()
        self._test_step_post_reboot(
            attributes_after_reboot=attributes_after_reboot)
        mock_deploying_error_handler.assert_called_once()

    @mock.patch.object(redfish_utils, 'get_system', autospec=True)
    def test_factory_reset_fail(self, mock_get_system):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            bios = mock_get_system(task.node).bios
            bios.reset_bios.side_effect = sushy.exceptions.SushyError
            self.assertRaisesRegex(
                exception.RedfishError, 'BIOS factory reset failed',
                task.driver.bios.factory_reset, task)

    @mock.patch.object(redfish_utils, 'get_system', autospec=True)
    def test_factory_reset_not_supported(self, mock_get_system):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            mock_get_system.return_value = NoBiosSystem()
            self.assertRaisesRegex(
                exception.RedfishError, 'BIOS factory reset failed',
                task.driver.bios.factory_reset, task)

    @mock.patch.object(redfish_utils, 'get_system', autospec=True)
    def test_apply_configuration_not_supported(self, mock_get_system):
        settings = [{'name': 'ProcTurboMode', 'value': 'Disabled'},
                    {'name': 'NicBoot1', 'value': 'NetworkBoot'}]
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            mock_get_system.return_value = NoBiosSystem()
            self.assertRaisesRegex(exception.RedfishError,
                                   'BIOS settings are not supported',
                                   task.driver.bios.apply_configuration,
                                   task, settings)
            mock_get_system.assert_called_once_with(task.node)

    @mock.patch.object(redfish_utils, 'get_system', autospec=True)
    def test_check_bios_attrs(self, mock_get_system):
        settings = [{'name': 'ProcTurboMode', 'value': 'Disabled'},
                    {'name': 'NicBoot1', 'value': 'NetworkBoot'}]
        requested_attrs = {'ProcTurboMode': 'Enabled',
                           'NicBoot1': 'NetworkBoot'}
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            attributes = mock_get_system(task.node).bios.attributes
            task.node.driver_internal_info[
                'post_config_reboot_requested'] = True
            task.node.driver_internal_info[
                'requested_bios_attrs'] = requested_attrs
            task.driver.bios._check_bios_attrs = mock.MagicMock()
            task.driver.bios.apply_configuration(task, settings)
            task.driver.bios._check_bios_attrs \
                .assert_called_once_with(task, attributes, requested_attrs)

    @mock.patch.object(redfish_utils, 'get_system', autospec=True)
    def test_apply_configuration_fail(self, mock_get_system):
        settings = [{'name': 'ProcTurboMode', 'value': 'Disabled'},
                    {'name': 'NicBoot1', 'value': 'NetworkBoot'}]
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            bios = mock_get_system(task.node).bios
            bios.set_attributes.side_effect = sushy.exceptions.SushyError
            self.assertRaisesRegex(
                exception.RedfishError, 'BIOS apply configuration failed',
                task.driver.bios.apply_configuration, task, settings)

    @mock.patch.object(redfish_utils, 'get_system', autospec=True)
    def test_post_configuration(self, mock_get_system):
        settings = [{'name': 'ProcTurboMode', 'value': 'Disabled'},
                    {'name': 'NicBoot1', 'value': 'NetworkBoot'}]
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            task.driver.bios.post_configuration = mock.MagicMock()
            task.driver.bios.apply_configuration(task, settings)
            task.driver.bios.post_configuration\
                .assert_called_once_with(task, settings)

    @mock.patch.object(redfish_boot.RedfishVirtualMediaBoot, 'prepare_ramdisk',
                       spec_set=True, autospec=True)
    @mock.patch.object(deploy_utils, 'build_agent_options', autospec=True)
    @mock.patch.object(redfish_utils, 'get_system', autospec=True)
    @mock.patch.object(manager_utils, 'node_power_action', autospec=True)
    def test_apply_configuration_apply_time_immediate(self, mock_power_action,
                                                      mock_get_system,
                                                      mock_build_agent_options,
                                                      mock_prepare):
        settings = [{'name': 'ProcTurboMode', 'value': 'Disabled'},
                    {'name': 'NicBoot1', 'value': 'NetworkBoot'}]
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            bios = mock_get_system(task.node).bios
            bios.supported_apply_times = ['immediate']

            task.driver.bios.apply_configuration(task, settings)

            bios.set_attributes.assert_called_once_with(
                {s['name']: s['value'] for s in settings},
                apply_time=None)

    @mock.patch.object(redfish_boot.RedfishVirtualMediaBoot, 'prepare_ramdisk',
                       spec_set=True, autospec=True)
    @mock.patch.object(deploy_utils, 'build_agent_options', autospec=True)
    @mock.patch.object(redfish_utils, 'get_system', autospec=True)
    @mock.patch.object(manager_utils, 'node_power_action', autospec=True)
    def test_apply_configuration_apply_time_on_reset(self, mock_power_action,
                                                     mock_get_system,
                                                     mock_build_agent_options,
                                                     mock_prepare):
        settings = [{'name': 'ProcTurboMode', 'value': 'Disabled'},
                    {'name': 'NicBoot1', 'value': 'NetworkBoot'}]
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            bios = mock_get_system(task.node).bios
            bios.supported_apply_times = [sushy.APPLY_TIME_ON_RESET]

            task.driver.bios.apply_configuration(task, settings)

            bios.set_attributes.assert_called_once_with(
                {s['name']: s['value'] for s in settings},
                apply_time=sushy.APPLY_TIME_ON_RESET)

    @mock.patch.object(redfish_boot.RedfishVirtualMediaBoot, 'prepare_ramdisk',
                       spec_set=True, autospec=True)
    @mock.patch.object(deploy_utils, 'build_agent_options', autospec=True)
    @mock.patch.object(redfish_utils, 'get_system', autospec=True)
    @mock.patch.object(manager_utils, 'node_power_action', autospec=True)
    def test_apply_configuration_no_supported_apply_times(
            self, mock_power_action, mock_get_system, mock_build_agent_options,
            mock_prepare):
        settings = [{'name': 'ProcTurboMode', 'value': 'Disabled'},
                    {'name': 'NicBoot1', 'value': 'NetworkBoot'}]
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            bios = mock_get_system(task.node).bios
            bios.supported_apply_times = None

            task.driver.bios.apply_configuration(task, settings)

            bios.set_attributes.assert_called_once_with(
                {s['name']: s['value'] for s in settings},
                apply_time=None)

    @mock.patch.object(redfish_boot.RedfishVirtualMediaBoot, 'prepare_ramdisk',
                       spec_set=True, autospec=True)
    @mock.patch.object(deploy_utils, 'build_agent_options', autospec=True)
    @mock.patch.object(redfish_utils, 'get_system', autospec=True)
    @mock.patch.object(manager_utils, 'node_power_action', autospec=True)
    def test_apply_configuration_no_apply_time_attr(
            self, mock_power_action, mock_get_system, mock_build_agent_options,
            mock_prepare):
        settings = [{'name': 'ProcTurboMode', 'value': 'Disabled'},
                    {'name': 'NicBoot1', 'value': 'NetworkBoot'}]
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            bios = mock_get_system(task.node).bios
            del bios.supported_apply_times

            task.driver.bios.apply_configuration(task, settings)

            bios.set_attributes.assert_called_once_with(
                {s['name']: s['value'] for s in settings},
                apply_time=None)


@mock.patch('oslo_utils.eventletutils.EventletEvent.wait',
            lambda *args, **kwargs: None)
class RedfishBiosRegistryTestCase(db_base.DbTestCase):

    def setUp(self):
        super(RedfishBiosRegistryTestCase, self).setUp()
        self.config(enabled_bios_interfaces=['redfish'],
                    enabled_hardware_types=['redfish'],
                    enabled_power_interfaces=['redfish'],
                    enabled_boot_interfaces=['redfish-virtual-media'],
                    enabled_management_interfaces=['redfish'])
        self.node = obj_utils.create_test_node(
            self.context, driver='redfish', driver_info=INFO_DICT)

        self.settings = {'SystemModelName': 'UltraSumma',
                         'DcuStreamPrefetcher': 'Enabled',
                         'BootDelay': 10}

        class AttributeField():

            def __init__(self):
                self.name = None
                self.allowable_values = None
                self.attribute_type = None
                self.lower_bound = None
                self.max_length = None
                self.min_length = None
                self.read_only = None
                self.reset_required = None
                self.type = None
                self.unique = None
                self.upper_bound = None

        class AttributeRegistryEntryField():

            def __init__(self, num_entries):
                self.attributes = []
                for _ in range(num_entries):
                    self.attributes.append(AttributeField())

        class AttributeRegistryTest():

            def __init__(self, num_entries):
                self.registry_entries = AttributeRegistryEntryField(
                    num_entries)

        self.registry = AttributeRegistryTest(4)
        self.registry.registry_entries.attributes[0].name = "SystemModelName"
        self.registry.registry_entries.attributes[0].attribute_type = "String"
        self.registry.registry_entries.attributes[0].max_length = 32
        self.registry.registry_entries.attributes[0].read_only = True
        self.registry.registry_entries.attributes[0].unique = True
        self.registry.registry_entries.attributes[1].name =\
            "DcuStreamPrefetcher"
        self.registry.registry_entries.attributes[1].attribute_type =\
            "Enumeration"
        self.registry.registry_entries.attributes[1].read_only = False
        self.registry.registry_entries.attributes[1].allowable_values =\
            [{'ValueName': 'Enabled', 'ValueDisplayName': 'Enabled'},
             {'ValueDisplayName': 'Disabled'},
             {'Invalid': 'banana'}]
        self.registry.registry_entries.attributes[2].name = "BootDelay"
        self.registry.registry_entries.attributes[2].attribute_type = "Integer"
        self.registry.registry_entries.attributes[2].lower_bound = 5
        self.registry.registry_entries.attributes[2].upper_bound = 30
        self.registry.registry_entries.attributes[2].reset_required = True
        self.registry.registry_entries.attributes[3].name = "SomeAttribute"
        self.registry.registry_entries.attributes[3].attribute_type = "String"
        self.registry.registry_entries.attributes[3].max_length = 32
        self.registry.registry_entries.attributes[3].read_only = True

        self.expected_no_registry = [
            {'name': 'SystemModelName', 'value': 'UltraSumma'},
            {'name': 'DcuStreamPrefetcher', 'value': 'Enabled'},
            {'name': 'BootDelay', 'value': 10}]

    @mock.patch.object(objects, 'BIOSSettingList', autospec=True)
    @mock.patch.object(redfish_utils, 'get_system', autospec=True)
    def test_cache_bios_registry_save(self, mock_get_system,
                                      mock_setting_list):
        create_list = []
        update_list = []
        delete_list = []
        nochange_list = []
        mock_setting_list.sync_node_setting.return_value = (
            create_list, update_list, delete_list, nochange_list
        )

        expected = [{'name': 'SystemModelName', 'value': 'UltraSumma',
                     'allowable_values': None, 'lower_bound': None,
                     'max_length': 32, 'min_length': None, 'read_only': True,
                     'reset_required': None, 'attribute_type': 'String',
                     'unique': True, 'upper_bound': None},
                    {'name': 'DcuStreamPrefetcher', 'value': 'Enabled',
                     'allowable_values': ['Enabled', 'Disabled'],
                     'lower_bound': None, 'max_length': None,
                     'min_length': None, 'read_only': False,
                     'reset_required': None, 'attribute_type':
                     'Enumeration', 'unique': None, 'upper_bound': None},
                    {'name': 'BootDelay', 'value': 10,
                     'allowable_values': None, 'lower_bound': 5,
                     'max_length': None, 'min_length': None, 'read_only': None,
                     'reset_required': True, 'attribute_type': 'Integer',
                     'unique': None, 'upper_bound': 30}]

        mock_get_system.return_value.bios.attributes = self.settings
        mock_get_system.return_value.bios.get_attribute_registry.\
            return_value = self.registry

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            task.driver.bios.cache_bios_settings(task)
            mock_get_system.assert_called_once_with(task.node)
            mock_setting_list.sync_node_setting.assert_called_once_with(
                task.context, task.node.id, expected)

    @mock.patch.object(objects, 'BIOSSettingList', autospec=True)
    @mock.patch.object(redfish_utils, 'get_system', autospec=True)
    def test_cache_empty_bios_registry(self, mock_get_system,
                                       mock_setting_list):
        create_list = []
        update_list = []
        delete_list = []
        nochange_list = []
        mock_setting_list.sync_node_setting.return_value = (
            create_list, update_list, delete_list, nochange_list
        )

        mock_get_system.return_value.bios.attributes = self.settings
        mock_get_system.return_value.bios.get_attribute_registry.\
            return_value = {}

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            task.driver.bios.cache_bios_settings(task)
            mock_setting_list.sync_node_setting.assert_called_once_with(
                task.context, task.node.id, self.expected_no_registry)

    @mock.patch.object(objects, 'BIOSSettingList', autospec=True)
    @mock.patch.object(redfish_utils, 'get_system', autospec=True)
    def test_cache_no_bios_registry(self, mock_get_system,
                                    mock_setting_list):
        create_list = []
        update_list = []
        delete_list = []
        nochange_list = []
        mock_setting_list.sync_node_setting.return_value = (
            create_list, update_list, delete_list, nochange_list
        )

        mock_get_system.return_value.bios.attributes = self.settings
        mock_get_system.return_value.bios.get_attribute_registry.\
            return_value = None

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            task.driver.bios.cache_bios_settings(task)
            mock_setting_list.sync_node_setting.assert_called_once_with(
                task.context, task.node.id, self.expected_no_registry)

    @mock.patch.object(objects, 'BIOSSettingList', autospec=True)
    @mock.patch.object(redfish_utils, 'get_system', autospec=True)
    def test_cache_exception_bios_registry(self, mock_get_system,
                                           mock_setting_list):
        create_list = []
        update_list = []
        delete_list = []
        nochange_list = []
        mock_setting_list.sync_node_setting.return_value = (
            create_list, update_list, delete_list, nochange_list
        )

        mock_get_system.return_value.bios.attributes = self.settings

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            bios = mock_get_system(task.node).bios
            bios.reset_bios.side_effect = sushy.exceptions.SushyError

            task.driver.bios.cache_bios_settings(task)
            mock_setting_list.sync_node_setting.assert_called_once_with(
                task.context, task.node.id, self.expected_no_registry)
