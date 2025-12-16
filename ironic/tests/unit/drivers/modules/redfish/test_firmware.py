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

import datetime
import json
import time
from unittest import mock

from oslo_config import cfg
from oslo_utils import timeutils
import sushy

from ironic.common import exception
from ironic.common import states
from ironic.conductor import task_manager
from ironic.conductor import utils as manager_utils
from ironic.conf import CONF
from ironic.drivers.modules import deploy_utils
from ironic.drivers.modules.redfish import firmware as redfish_fw
from ironic.drivers.modules.redfish import firmware_utils
from ironic.drivers.modules.redfish import utils as redfish_utils
from ironic import objects
from ironic.tests.unit.db import base as db_base
from ironic.tests.unit.db import utils as db_utils
from ironic.tests.unit.objects import utils as obj_utils

INFO_DICT = db_utils.get_test_redfish_info()


class RedfishFirmwareTestCase(db_base.DbTestCase):

    def setUp(self):
        super(RedfishFirmwareTestCase, self).setUp()
        self.config(enabled_bios_interfaces=['redfish'],
                    enabled_hardware_types=['redfish'],
                    enabled_power_interfaces=['redfish'],
                    enabled_boot_interfaces=['redfish-virtual-media'],
                    enabled_management_interfaces=['redfish'],
                    enabled_firmware_interfaces=['redfish'])
        self.node = obj_utils.create_test_node(
            self.context, driver='redfish', driver_info=INFO_DICT)

    def _mock_exc_fwup_side_effect(self, firmware_interface, node,
                                   update_service, settings_list):
        """Helper to simulate _execute_firmware_update behavior.

        The real _execute_firmware_update:
        1. Adds a task_monitor field to the settings
        2. Calls component-specific setup methods

        This helper replicates that behavior for tests that mock
        this method to avoid JSON serialization issues.

        :param firmware_interface: The firmware interface instance (unused,
                                   but passed by mock framework)
        :param node: The node being updated
        :param update_service: The update service
        :param settings_list: The settings list
        """
        settings_list[0]['task_monitor'] = '/redfish/v1/TaskService/Tasks/1'

        # Simulate component-specific setup that now happens inside
        # _execute_firmware_update
        fw_upd = settings_list[0]
        component = fw_upd.get('component', '')

        # Call the actual setup method based on component type
        # This ensures the driver_internal_info is set correctly
        if component == redfish_utils.BMC:
            firmware_interface._setup_bmc_update_monitoring(node, fw_upd)
        elif component.startswith(redfish_utils.NIC_COMPONENT_PREFIX):
            firmware_interface._setup_nic_update_monitoring(node)
        elif component == redfish_utils.BIOS:
            firmware_interface._setup_bios_update_monitoring(node)
        else:
            firmware_interface._setup_default_update_monitoring(node, fw_upd)

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
            task.driver.firmware.validate(task)
            mock_parse_driver_info.assert_called_once_with(task.node)

    @mock.patch.object(redfish_fw, 'LOG', autospec=True)
    @mock.patch.object(redfish_utils, 'get_system', autospec=True)
    @mock.patch.object(redfish_utils, 'get_manager', autospec=True)
    @mock.patch.object(redfish_utils, 'get_chassis', autospec=True)
    @mock.patch.object(objects.FirmwareComponentList,
                       'sync_firmware_components', autospec=True)
    def test_missing_all_components(self, sync_fw_cmp_mock, chassis_mock,
                                    manager_mock, system_mock, log_mock):

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            system_mock.return_value.identity = "System1"
            manager_mock.return_value.identity = "Manager1"
            system_mock.return_value.bios_version = None
            manager_mock.return_value.firmware_version = None

            netadp = mock.MagicMock()
            netadp.get_members.return_value = []
            chassis_mock.return_value.network_adapters = netadp

            self.assertRaises(exception.UnsupportedDriverExtension,
                              task.driver.firmware.cache_firmware_components,
                              task)

            sync_fw_cmp_mock.assert_not_called()
            error_msg = (
                'Cannot retrieve firmware for node %s: '
                'no supported components'
                % self.node.uuid)
            log_mock.error.assert_called_once_with(error_msg)

            debug_calls = [
                mock.call('Could not retrieve BiosVersion in node '
                          '%(node_uuid)s system %(system)s',
                          {'node_uuid': self.node.uuid,
                           'system': "System1"}),
                mock.call('Could not retrieve FirmwareVersion in node '
                          '%(node_uuid)s manager %(manager)s',
                          {'node_uuid': self.node.uuid,
                           'manager': "Manager1"}),
                mock.call('Could not retrieve Firmware Package Version '
                          'from NetworkAdapters on node %(node_uuid)s',
                          {'node_uuid': self.node.uuid})]
            log_mock.debug.assert_has_calls(debug_calls)

    @mock.patch.object(redfish_fw, 'LOG', autospec=True)
    @mock.patch.object(redfish_utils, 'get_system', autospec=True)
    @mock.patch.object(redfish_utils, 'get_manager', autospec=True)
    @mock.patch.object(objects.FirmwareComponentList,
                       'sync_firmware_components', autospec=True)
    @mock.patch.object(objects, 'FirmwareComponent', spec_set=True,
                       autospec=True)
    def test_missing_bios_component(self, fw_cmp_mock, sync_fw_cmp_mock,
                                    manager_mock, system_mock, log_mock):
        create_list = [{'component': 'bmc', 'current_version': 'v1.0.0'}]
        sync_fw_cmp_mock.return_value = (
            create_list, [], []
        )

        bmc_component = {'component': 'bmc', 'current_version': 'v1.0.0',
                         'node_id': self.node.id}

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            system_mock.return_value.identity = "System1"
            system_mock.return_value.bios_version = None
            manager_mock.return_value.firmware_version = "v1.0.0"

            task.driver.firmware.cache_firmware_components(task)
            system_mock.assert_called_once_with(task.node)

            log_mock.debug.assert_any_call(
                'Could not retrieve BiosVersion in node '
                '%(node_uuid)s system %(system)s',
                {'node_uuid': self.node.uuid, 'system': 'System1'})
            sync_fw_cmp_mock.assert_called_once_with(
                task.context, task.node.id,
                [{'component': 'bmc', 'current_version': 'v1.0.0'}])
            self.assertTrue(fw_cmp_mock.called)
            fw_cmp_mock.assert_called_once_with(task.context, **bmc_component)

    @mock.patch.object(redfish_fw, 'LOG', autospec=True)
    @mock.patch.object(redfish_utils, 'get_system', autospec=True)
    @mock.patch.object(redfish_utils, 'get_manager', autospec=True)
    @mock.patch.object(objects.FirmwareComponentList,
                       'sync_firmware_components', autospec=True)
    @mock.patch.object(objects, 'FirmwareComponent', spec_set=True,
                       autospec=True)
    def test_missing_bmc_component(self, fw_cmp_mock, sync_fw_cmp_mock,
                                   manager_mock, system_mock, log_mock):
        create_list = [{'component': 'bios', 'current_version': 'v1.0.0'}]
        sync_fw_cmp_mock.return_value = (
            create_list, [], []
        )

        bios_component = {'component': 'bios', 'current_version': 'v1.0.0',
                          'node_id': self.node.id}

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            manager_mock.return_value.identity = "Manager1"
            manager_mock.return_value.firmware_version = None
            system_mock.return_value.bios_version = "v1.0.0"
            task.driver.firmware.cache_firmware_components(task)

            log_mock.debug.assert_any_call(
                'Could not retrieve FirmwareVersion in node '
                '%(node_uuid)s manager %(manager)s',
                {'node_uuid': self.node.uuid, 'manager': "Manager1"})
            system_mock.assert_called_once_with(task.node)
            sync_fw_cmp_mock.assert_called_once_with(
                task.context, task.node.id,
                [{'component': 'bios', 'current_version': 'v1.0.0'}])
            self.assertTrue(fw_cmp_mock.called)
            fw_cmp_mock.assert_called_once_with(task.context, **bios_component)

    @mock.patch.object(redfish_fw, 'LOG', autospec=True)
    @mock.patch.object(redfish_utils, 'get_system', autospec=True)
    @mock.patch.object(redfish_utils, 'get_manager', autospec=True)
    @mock.patch.object(redfish_utils, 'get_chassis', autospec=True)
    @mock.patch.object(objects, 'FirmwareComponentList', autospec=True)
    @mock.patch.object(objects, 'FirmwareComponent', spec_set=True,
                       autospec=True)
    def test_create_all_components(self, fw_cmp_mock, fw_cmp_list_mock,
                                   chassis_mock, manager_mock, system_mock,
                                   log_mock):
        create_list = [{'component': 'bios', 'current_version': 'v1.0.0'},
                       {'component': 'bmc', 'current_version': 'v1.0.0'},
                       {'component': 'nic:NIC1', 'current_version': '1'}]
        fw_cmp_list_mock.sync_firmware_components.return_value = (
            create_list, [], []
        )

        bios_component = {'component': 'bios', 'current_version': 'v1.0.0',
                          'node_id': self.node.id}

        bmc_component = {'component': 'bmc', 'current_version': 'v1.0.0',
                         'node_id': self.node.id}

        nic_component = {'component': 'nic:NIC1', 'current_version': '1',
                         'node_id': self.node.id}

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            manager_mock.return_value.firmware_version = "v1.0.0"
            system_mock.return_value.bios_version = "v1.0.0"
            chassis_mock
            netadp_ctrl = mock.MagicMock()
            netadp_ctrl.firmware_package_version = "1"
            netadp = mock.MagicMock()
            netadp.identity = 'NIC1'
            netadp.controllers = [netadp_ctrl]
            net_adapters = mock.MagicMock()
            net_adapters.get_members.return_value = [netadp]
            chassis_mock.return_value.network_adapters = net_adapters
            task.driver.firmware.cache_firmware_components(task)

            log_mock.warning.assert_not_called()
            log_mock.debug.assert_not_called()
            system_mock.assert_called_once_with(task.node)
            fw_cmp_list_mock.sync_firmware_components.assert_called_once_with(
                task.context, task.node.id,
                [{'component': 'bios', 'current_version': 'v1.0.0'},
                 {'component': 'bmc', 'current_version': 'v1.0.0'},
                 {'component': 'nic:NIC1', 'current_version': '1'}])
            fw_cmp_calls = [
                mock.call(task.context, **bios_component),
                mock.call().create(),
                mock.call(task.context, **bmc_component),
                mock.call().create(),
                mock.call(task.context, **nic_component),
                mock.call().create()
            ]
            fw_cmp_mock.assert_has_calls(fw_cmp_calls)

    @mock.patch.object(redfish_fw, 'LOG', autospec=True)
    @mock.patch.object(redfish_utils, 'get_chassis', autospec=True)
    @mock.patch.object(redfish_utils, 'get_manager', autospec=True)
    @mock.patch.object(redfish_utils, 'get_system', autospec=True)
    @mock.patch.object(objects, 'FirmwareComponentList', autospec=True)
    def test_get_chassis_redfish_error(self, sync_fw_cmp_mock, system_mock,
                                       manager_mock, chassis_mock, log_mock):
        system_mock.return_value.identity = "System1"
        system_mock.return_value.bios_version = '1.0.0'
        manager_mock.return_value.identity = "Manager1"
        manager_mock.return_value.firmware_version = '1.0.0'

        chassis_mock.side_effect = exception.RedfishError('not found')

        sync_fw_cmp_mock.sync_firmware_components.return_value = (
            [{'component': 'bios', 'current_version': '1.0.0'},
             {'component': 'bmc', 'current_version': '1.0.0'},],
            [], [])

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            task.driver.firmware.cache_firmware_components(task)

        log_mock.debug.assert_any_call(
            'No chassis available to retrieve NetworkAdapters firmware '
            'information on node %(node_uuid)s',
            {'node_uuid': self.node.uuid}
        )

    @mock.patch.object(redfish_fw, 'LOG', autospec=True)
    @mock.patch.object(redfish_utils, 'get_system', autospec=True)
    @mock.patch.object(redfish_utils, 'get_manager', autospec=True)
    @mock.patch.object(objects, 'FirmwareComponentList', autospec=True)
    def test_retrieve_nic_components_redfish_connection_error(
            self, sync_fw_cmp_mock, manager_mock, system_mock, log_mock):
        """Test that RedfishConnectionError during NIC retrieval is handled."""
        system_mock.return_value.identity = "System1"
        system_mock.return_value.bios_version = '1.0.0'
        manager_mock.return_value.identity = "Manager1"
        manager_mock.return_value.firmware_version = '1.0.0'

        sync_fw_cmp_mock.sync_firmware_components.return_value = (
            [{'component': 'bios', 'current_version': '1.0.0'},
             {'component': 'bmc', 'current_version': '1.0.0'}],
            [], [])

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            with mock.patch.object(task.driver.firmware,
                                   'retrieve_nic_components',
                                   autospec=True) as mock_retrieve:
                connection_error = exception.RedfishError(
                    'Connection failed')
                mock_retrieve.side_effect = connection_error

                task.driver.firmware.cache_firmware_components(task)

        # Verify warning log for exception is called
        log_mock.warning.assert_any_call(
            'Unable to access NetworkAdapters on node %(node_uuid)s, '
            'Error: %(error)s',
            {'node_uuid': self.node.uuid, 'error': connection_error}
        )

        # Verify debug log for empty NIC list is NOT called
        # (since we caught an exception, not an empty list)
        debug_calls = [call for call in log_mock.debug.call_args_list
                       if 'Could not retrieve Firmware Package Version from '
                          'NetworkAdapters' in str(call)]
        self.assertEqual(len(debug_calls), 0)

    @mock.patch.object(redfish_fw, 'LOG', autospec=True)
    @mock.patch.object(redfish_utils, 'get_system', autospec=True)
    @mock.patch.object(redfish_utils, 'get_manager', autospec=True)
    @mock.patch.object(objects, 'FirmwareComponentList', autospec=True)
    def test_retrieve_nic_components_sushy_bad_request_error(
            self, sync_fw_cmp_mock, manager_mock, system_mock, log_mock):
        """Test that sushy BadRequestError during NIC retrieval is handled."""
        system_mock.return_value.identity = "System1"
        system_mock.return_value.bios_version = '1.0.0'
        manager_mock.return_value.identity = "Manager1"
        manager_mock.return_value.firmware_version = '1.0.0'

        sync_fw_cmp_mock.sync_firmware_components.return_value = (
            [{'component': 'bios', 'current_version': '1.0.0'},
             {'component': 'bmc', 'current_version': '1.0.0'}],
            [], [])

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            with mock.patch.object(task.driver.firmware,
                                   'retrieve_nic_components',
                                   autospec=True) as mock_retrieve:
                bad_request_error = sushy.exceptions.BadRequestError(
                    method='GET', url='/redfish/v1/Chassis/1/NetworkAdapters',
                    response=mock.Mock(status_code=400))
                mock_retrieve.side_effect = bad_request_error

                task.driver.firmware.cache_firmware_components(task)

        # Verify warning log for exception is called
        log_mock.warning.assert_any_call(
            'Unable to access NetworkAdapters on node %(node_uuid)s, '
            'Error: %(error)s',
            {'node_uuid': self.node.uuid, 'error': bad_request_error}
        )

        # Verify debug log for empty NIC list is NOT called
        # (since we caught an exception, not an empty list)
        debug_calls = [call for call in log_mock.debug.call_args_list
                       if 'Could not retrieve Firmware Package Version from '
                          'NetworkAdapters' in str(call)]
        self.assertEqual(len(debug_calls), 0)

    @mock.patch.object(redfish_fw, 'LOG', autospec=True)
    @mock.patch.object(redfish_utils, 'get_system', autospec=True)
    @mock.patch.object(redfish_utils, 'get_manager', autospec=True)
    @mock.patch.object(redfish_utils, 'get_chassis', autospec=True)
    @mock.patch.object(objects, 'FirmwareComponentList', autospec=True)
    @mock.patch.object(objects, 'FirmwareComponent', spec_set=True,
                       autospec=True)
    def test_retrieve_nic_components_invalid_firmware_version(
            self, fw_cmp_mock, fw_cmp_list, chassis_mock, manager_mock,
            system_mock, log_mock):
        """Test that NIC components with missing versions are skipped."""
        for invalid_version in [None, ""]:
            fw_cmp_list.reset_mock()
            fw_cmp_mock.reset_mock()
            log_mock.reset_mock()

            create_list = [{'component': 'bios', 'current_version': 'v1.0.0'},
                           {'component': 'bmc', 'current_version': 'v1.0.0'}]
            fw_cmp_list.sync_firmware_components.return_value = (
                create_list, [], []
            )

            bios_component = {'component': 'bios',
                              'current_version': 'v1.0.0',
                              'node_id': self.node.id}

            bmc_component = {'component': 'bmc', 'current_version': 'v1.0.0',
                             'node_id': self.node.id}

            with task_manager.acquire(self.context, self.node.uuid,
                                      shared=True) as task:
                manager_mock.return_value.firmware_version = "v1.0.0"
                system_mock.return_value.bios_version = "v1.0.0"

                netadp_ctrl = mock.MagicMock()
                netadp_ctrl.firmware_package_version = invalid_version
                netadp = mock.MagicMock()
                netadp.identity = 'NIC1'
                netadp.controllers = [netadp_ctrl]
                net_adapters = mock.MagicMock()
                net_adapters.get_members.return_value = [netadp]
                chassis_mock.return_value.network_adapters = net_adapters
                task.driver.firmware.cache_firmware_components(task)

                fw_cmp_list.sync_firmware_components.assert_called_once_with(
                    task.context, task.node.id,
                    [{'component': 'bios', 'current_version': 'v1.0.0'},
                     {'component': 'bmc', 'current_version': 'v1.0.0'}])

                fw_cmp_calls = [
                    mock.call(task.context, **bios_component),
                    mock.call().create(),
                    mock.call(task.context, **bmc_component),
                    mock.call().create()
                ]
                fw_cmp_mock.assert_has_calls(fw_cmp_calls)
                log_mock.warning.assert_not_called()

    @mock.patch.object(redfish_fw, 'LOG', autospec=True)
    @mock.patch.object(redfish_utils, 'get_system', autospec=True)
    @mock.patch.object(redfish_utils, 'get_manager', autospec=True)
    @mock.patch.object(redfish_utils, 'get_chassis', autospec=True)
    @mock.patch.object(objects, 'FirmwareComponentList', autospec=True)
    def test_retrieve_nic_components_network_adapters_none(
            self, fw_cmp_list, chassis_mock, manager_mock,
            system_mock, log_mock):
        """Test that None network_adapters is handled gracefully."""
        fw_cmp_list.sync_firmware_components.return_value = (
            [{'component': 'bios', 'current_version': '1.0.0'},
             {'component': 'bmc', 'current_version': '1.0.0'}],
            [], [])

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            system_mock.return_value.bios_version = '1.0.0'
            manager_mock.return_value.firmware_version = '1.0.0'
            # network_adapters is None
            chassis_mock.return_value.network_adapters = None

            task.driver.firmware.cache_firmware_components(task)

        # Should log at debug level, not warning
        log_mock.debug.assert_any_call(
            'NetworkAdapters not available on chassis for '
            'node %(node_uuid)s',
            {'node_uuid': self.node.uuid}
        )
        log_mock.warning.assert_not_called()

    @mock.patch.object(redfish_fw, 'LOG', autospec=True)
    @mock.patch.object(redfish_utils, 'get_system', autospec=True)
    @mock.patch.object(redfish_utils, 'get_manager', autospec=True)
    @mock.patch.object(redfish_utils, 'get_chassis', autospec=True)
    @mock.patch.object(objects, 'FirmwareComponentList', autospec=True)
    def test_retrieve_nic_components_missing_attribute_error(
            self, fw_cmp_list, chassis_mock, manager_mock,
            system_mock, log_mock):
        """Test that MissingAttributeError is handled gracefully."""
        fw_cmp_list.sync_firmware_components.return_value = (
            [{'component': 'bios', 'current_version': '1.0.0'},
             {'component': 'bmc', 'current_version': '1.0.0'}],
            [], [])

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            system_mock.return_value.bios_version = '1.0.0'
            manager_mock.return_value.firmware_version = '1.0.0'
            # network_adapters raises MissingAttributeError
            type(chassis_mock.return_value).network_adapters = (
                mock.PropertyMock(
                    side_effect=sushy.exceptions.MissingAttributeError))

            task.driver.firmware.cache_firmware_components(task)

        # Should log at debug level, not warning
        log_mock.debug.assert_any_call(
            'NetworkAdapters not available on chassis for '
            'node %(node_uuid)s',
            {'node_uuid': self.node.uuid}
        )
        log_mock.warning.assert_not_called()

    @mock.patch.object(redfish_utils, 'LOG', autospec=True)
    @mock.patch.object(redfish_utils, '_get_connection', autospec=True)
    def test_missing_updateservice(self, conn_mock, log_mock):
        settings = [{'component': 'bmc', 'url': 'http://upfwbmc/v2.0.0'}]
        conn_mock.side_effect = sushy.exceptions.MissingAttributeError(
            attribute='UpdateService', resource='redfish/v1')
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            error_msg = ('The attribute UpdateService is missing from the '
                         'resource redfish/v1')
            self.assertRaisesRegex(
                exception.RedfishError, error_msg,
                task.driver.firmware.update,
                task, settings)

    @mock.patch.object(redfish_fw, 'LOG', autospec=True)
    @mock.patch.object(redfish_utils, 'get_update_service', autospec=True)
    @mock.patch.object(redfish_utils, 'get_system_collection', autospec=True)
    def test_missing_simple_update_action(self, get_systems_collection_mock,
                                          update_service_mock, log_mock):
        settings = [{'component': 'bmc', 'url': 'http://upfwbmc/v2.0.0'}]
        update_service = update_service_mock.return_value
        update_service.simple_update.side_effect = \
            sushy.exceptions.MissingAttributeError(
                attribute='#UpdateService.SimpleUpdate',
                resource='redfish/v1/UpdateService')
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:

            self.assertRaises(
                exception.RedfishError,
                task.driver.firmware.update,
                task, settings)
            expected_err_msg = (
                'The attribute #UpdateService.SimpleUpdate is missing '
                'from the resource redfish/v1/UpdateService')
            log_mock.error.assert_called_once_with(
                'The attribute #UpdateService.SimpleUpdate is missing '
                'on node %(node)s. Error: %(error)s',
                {'node': self.node.uuid, 'error': expected_err_msg})

            component = settings[0].get('component')
            url = settings[0].get('url')

            log_call = [
                mock.call('Updating Firmware on node %(node_uuid)s '
                          'with settings %(settings)s',
                          {'node_uuid': self.node.uuid,
                           'settings': settings}),
                mock.call('For node %(node)s serving firmware for '
                          '%(component)s from original location %(url)s',
                          {'node': self.node.uuid,
                           'component': component, 'url': url}),
                mock.call('Applying new firmware %(url)s for '
                          '%(component)s on node %(node_uuid)s',
                          {'url': url, 'component': component,
                           'node_uuid': self.node.uuid})
            ]
            log_mock.debug.assert_has_calls(log_call)

    @mock.patch.object(redfish_fw, 'LOG', autospec=True)
    def _test_invalid_settings(self, log_mock):
        step = self.node.clean_step
        settings = step['argsinfo'].get('settings', None)
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            self.assertRaises(
                exception.InvalidParameterValue,
                task.driver.firmware.update,
                task, settings)
            log_mock.debug.assert_not_called()

    @mock.patch.object(redfish_fw, 'LOG', autospec=True)
    def _test_invalid_settings_service(self, log_mock):
        step = self.node.service_step
        settings = step['argsinfo'].get('settings', None)
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            self.assertRaises(
                exception.InvalidParameterValue,
                task.driver.firmware.update,
                task, settings)
            log_mock.debug.assert_not_called()

    def test_invalid_component_in_settings(self):
        argsinfo = {'settings': [
            {'component': 'something', 'url': 'https://nic-update/v1.1.0'}
        ]}
        self.node.clean_step = {'priority': 100, 'interface': 'firmware',
                                'step': 'update',
                                'argsinfo': argsinfo}
        self.node.save()
        self._test_invalid_settings()

    def test_invalid_component_in_settings_service(self):
        argsinfo = {'settings': [
            {'component': 'something', 'url': 'https://nic-update/v1.1.0'}
        ]}
        self.node.service_step = {'priority': 100, 'interface': 'firmware',
                                  'step': 'update',
                                  'argsinfo': argsinfo}
        self.node.save()
        self._test_invalid_settings_service()

    def test_missing_required_field_in_settings(self):
        argsinfo = {'settings': [
            {'url': 'https://nic-update/v1.1.0'},
            {'component': "bmc"}
        ]}
        self.node.clean_step = {'priority': 100, 'interface': 'firmware',
                                'step': 'update',
                                'argsinfo': argsinfo}
        self.node.save()
        self._test_invalid_settings()

    def test_missing_required_field_in_settings_service(self):
        argsinfo = {'settings': [
            {'url': 'https://nic-update/v1.1.0'},
            {'component': "bmc"}
        ]}
        self.node.service_step = {'priority': 100, 'interface': 'firmware',
                                  'step': 'update',
                                  'argsinfo': argsinfo}
        self.node.save()
        self._test_invalid_settings_service()

    def test_empty_settings(self):
        argsinfo = {'settings': []}
        self.node.clean_step = {'priority': 100, 'interface': 'firmware',
                                'step': 'update',
                                'argsinfo': argsinfo}
        self.node.save()
        self._test_invalid_settings()

    def test_empty_settings_service(self):
        argsinfo = {'settings': []}
        self.node.service_step = {'priority': 100, 'interface': 'firmware',
                                  'step': 'update',
                                  'argsinfo': argsinfo}
        self.node.save()
        self._test_invalid_settings_service()

    @mock.patch.object(time, 'sleep', lambda seconds: None)
    def _generate_new_driver_internal_info(self, components=[], invalid=False,
                                           add_wait=False, wait=1):
        bmc_component = {'component': 'bmc', 'url': 'https://bmc/v1.0.1'}
        bios_component = {'component': 'bios', 'url': 'https://bios/v1.0.1'}
        if add_wait:
            wait_start_time = timeutils.utcnow() -\
                datetime.timedelta(minutes=1)
            bmc_component['wait_start_time'] = wait_start_time.isoformat()
            bios_component['wait_start_time'] = wait_start_time.isoformat()
            bmc_component['wait'] = wait
            bios_component['wait'] = wait

        self.node.clean_step = {'priority': 100, 'interface': 'bios',
                                'step': 'apply_configuration',
                                'argsinfo': {'settings': []}}

        updates = []
        if 'bmc' in components:
            self.node.clean_step['argsinfo']['settings'].append(
                bmc_component)
            bmc_component['task_monitor'] = '/task/1'
            updates.append(bmc_component)
        if 'bios' in components:
            self.node.clean_step['argsinfo']['settings'].append(
                bios_component)
            bios_component['task_monitor'] = '/task/2'
            updates.append(bios_component)

        if invalid:
            self.node.provision_state = states.CLEANING
            self.node.driver_internal_info = {'something': 'else'}
        else:
            self.node.provision_state = states.CLEANING
            self.node.driver_internal_info = {
                'redfish_fw_updates': updates,
            }
        self.node.save()

    def _generate_new_driver_internal_info_service(self, components=[],
                                                   invalid=False,
                                                   add_wait=False, wait=1):
        bmc_component = {'component': 'bmc', 'url': 'https://bmc/v1.0.1'}
        bios_component = {'component': 'bios', 'url': 'https://bios/v1.0.1'}
        if add_wait:
            wait_start_time = timeutils.utcnow() -\
                datetime.timedelta(minutes=1)
            bmc_component['wait_start_time'] = wait_start_time.isoformat()
            bios_component['wait_start_time'] = wait_start_time.isoformat()
            bmc_component['wait'] = wait
            bios_component['wait'] = wait

        self.node.service_step = {'priority': 100, 'interface': 'bios',
                                  'step': 'apply_configuration',
                                  'argsinfo': {'settings': []}}

        updates = []
        if 'bmc' in components:
            self.node.service_step['argsinfo']['settings'].append(
                bmc_component)
            bmc_component['task_monitor'] = '/task/1'
            updates.append(bmc_component)
        if 'bios' in components:
            self.node.service_step['argsinfo']['settings'].append(
                bios_component)
            bios_component['task_monitor'] = '/task/2'
            updates.append(bios_component)

        if invalid:
            self.node.provision_state = states.SERVICING
            self.node.driver_internal_info = {'something': 'else'}
        else:
            self.node.provision_state = states.SERVICING
            self.node.driver_internal_info = {
                'redfish_fw_updates': updates,
            }
        self.node.save()

    @mock.patch.object(task_manager, 'acquire', autospec=True)
    def _test__query_methods(self, acquire_mock):
        firmware = redfish_fw.RedfishFirmware()
        mock_manager = mock.Mock()
        node_list = [(self.node.uuid, 'redfish', '',
                      self.node.driver_internal_info)]
        mock_manager.iter_nodes.return_value = node_list
        task = mock.Mock(node=self.node,
                         driver=mock.Mock(firmware=firmware))
        acquire_mock.return_value = mock.MagicMock(
            __enter__=mock.MagicMock(return_value=task))

        firmware._check_node_redfish_firmware_update = mock.Mock()
        firmware._clear_updates = mock.Mock()

        # _query_update_status
        firmware._query_update_status(mock_manager, self.context)
        if not self.node.driver_internal_info.get('redfish_fw_updates'):
            firmware._check_node_redfish_firmware_update.assert_not_called()
        else:
            firmware._check_node_redfish_firmware_update.\
                assert_called_once_with(task)

        # _query_update_failed
        firmware._query_update_failed(mock_manager, self.context)
        if not self.node.driver_internal_info.get('redfish_fw_updates'):
            firmware._clear_updates.assert_not_called()
        else:
            firmware._clear_updates.assert_called_once_with(self.node)

    def test_redfish_fw_updates(self):
        self._generate_new_driver_internal_info(['bmc'])
        self._test__query_methods()

    def test_redfish_fw_updates_empty(self):
        self._generate_new_driver_internal_info(invalid=True)
        self._test__query_methods()

    def _test__check_node_redfish_firmware_update(self):
        firmware = redfish_fw.RedfishFirmware()
        firmware._continue_updates = mock.Mock()
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.upgrade_lock = mock.Mock()
            task.process_event = mock.Mock()
            firmware._check_node_redfish_firmware_update(task)
            return task, firmware

    @mock.patch.object(redfish_utils, 'get_update_service', autospec=True)
    @mock.patch.object(redfish_utils, 'get_task_monitor', autospec=True)
    def test_check_calls_touch_provisioning(self, mock_task_monitor,
                                            mock_get_update_service):
        """Test _check_node_redfish_firmware_update calls touch_provisioning.

        This prevents heartbeat timeouts for firmware updates that don't
        require the ramdisk agent (requires_ramdisk=False). By calling
        touch_provisioning on each poll, we keep provision_updated_at fresh.
        """
        self._generate_new_driver_internal_info(['bmc'])

        # Mock task still in progress
        mock_task_monitor.return_value.is_processing = True

        firmware = redfish_fw.RedfishFirmware()
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            with mock.patch.object(task.node, 'touch_provisioning',
                                   autospec=True) as mock_touch:
                firmware._check_node_redfish_firmware_update(task)

                # Verify touch_provisioning was called
                mock_touch.assert_called_once_with()

    @mock.patch.object(redfish_utils, 'get_update_service', autospec=True)
    def test_check_skips_touch_provisioning_on_conn_error(
            self, mock_get_update_service):
        """Test touch_provisioning is NOT called when BMC connection fails.

        When the BMC is unresponsive, we should NOT update
        provision_updated_at. This ensures the process eventually times
        out if the BMC never recovers, rather than being kept alive.
        """
        self._generate_new_driver_internal_info(['bmc'])

        # Mock connection error
        mock_get_update_service.side_effect = exception.RedfishConnectionError(
            'Connection failed')

        firmware = redfish_fw.RedfishFirmware()
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            with mock.patch.object(task.node, 'touch_provisioning',
                                   autospec=True) as mock_touch:
                firmware._check_node_redfish_firmware_update(task)

                # Verify touch_provisioning was NOT called on connection error
                mock_touch.assert_not_called()

    @mock.patch.object(redfish_fw.manager_utils, 'servicing_error_handler',
                       autospec=True)
    @mock.patch.object(redfish_utils, 'get_update_service', autospec=True)
    def test_check_overall_timeout_exceeded(self, mock_get_update_service,
                                            mock_error_handler):
        """Test firmware update fails when overall timeout is exceeded.

        This ensures firmware updates don't run indefinitely - if the
        overall timeout is exceeded, the update should fail with an error.
        """
        self._generate_new_driver_internal_info(['bmc'])

        # Set start time to 3 hours ago (exceeds 2 hour default timeout)
        past_time = (timeutils.utcnow()
                     - datetime.timedelta(hours=3)).isoformat()
        self.node.set_driver_internal_info('redfish_fw_update_start_time',
                                           past_time)
        self.node.save()

        firmware = redfish_fw.RedfishFirmware()
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            firmware._check_node_redfish_firmware_update(task)

            # Verify error handler was called with timeout message
            mock_error_handler.assert_called_once()
            call_args = mock_error_handler.call_args
            self.assertIn('exceeded', call_args[0][1].lower())
            self.assertIn('timeout', call_args[0][1].lower())

            # Verify the firmware update info was cleaned up
            task.node.refresh()
            self.assertIsNone(
                task.node.driver_internal_info.get('redfish_fw_updates'))
            self.assertIsNone(
                task.node.driver_internal_info.get(
                    'redfish_fw_update_start_time'))

    @mock.patch.object(redfish_utils, 'get_update_service', autospec=True)
    @mock.patch.object(redfish_utils, 'get_task_monitor', autospec=True)
    def test_check_overall_timeout_not_exceeded(self, mock_task_monitor,
                                                mock_get_update_service):
        """Test firmware update continues when timeout not exceeded."""
        self._generate_new_driver_internal_info(['bmc'])

        # Set start time to 1 hour ago (within 2 hour default timeout)
        past_time = (timeutils.utcnow()
                     - datetime.timedelta(hours=1)).isoformat()
        self.node.set_driver_internal_info('redfish_fw_update_start_time',
                                           past_time)
        self.node.save()

        # Mock task still in progress
        mock_task_monitor.return_value.is_processing = True

        firmware = redfish_fw.RedfishFirmware()
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            with mock.patch.object(task.node, 'touch_provisioning',
                                   autospec=True) as mock_touch:
                firmware._check_node_redfish_firmware_update(task)

                # Verify touch_provisioning was called (update continues)
                mock_touch.assert_called_once_with()

    @mock.patch.object(redfish_fw, 'LOG', autospec=True)
    @mock.patch.object(redfish_utils, 'get_update_service', autospec=True)
    def test_check_conn_error(self, get_us_mock, log_mock):
        self._generate_new_driver_internal_info(['bmc'])
        get_us_mock.side_effect = exception.RedfishConnectionError('Error')
        try:
            self._test__check_node_redfish_firmware_update()
        except exception.RedfishError as e:
            exception_error = e.kwargs.get('error')

            warning_calls = [
                mock.call('Unable to communicate with firmware update '
                          'service on node %(node)s. Will try again on '
                          'the next poll. Error: %(error)s',
                          {'node': self.node.uuid,
                           'error': exception_error})
            ]
            log_mock.warning.assert_has_calls(warning_calls)

    @mock.patch.object(redfish_fw, 'LOG', autospec=True)
    @mock.patch.object(redfish_utils, 'get_update_service', autospec=True)
    def test_check_update_wait_elapsed(self, get_us_mock, log_mock):
        mock_update_service = mock.Mock()
        get_us_mock.return_value = mock_update_service
        self._generate_new_driver_internal_info(['bmc'], add_wait=True)

        task, interface = self._test__check_node_redfish_firmware_update()
        debug_calls = [
            mock.call('Finished waiting after firmware update '
                      '%(firmware_image)s on node %(node)s. '
                      'Elapsed time: %(seconds)s seconds',
                      {'firmware_image': 'https://bmc/v1.0.1',
                       'node': self.node.uuid, 'seconds': 60})]
        log_mock.debug.assert_has_calls(debug_calls)
        interface._continue_updates.assert_called_once_with(
            task,
            mock_update_service,
            [{'component': 'bmc', 'url': 'https://bmc/v1.0.1',
              'task_monitor': '/task/1'}])

    @mock.patch.object(redfish_fw, 'LOG', autospec=True)
    @mock.patch.object(redfish_utils, 'get_update_service', autospec=True)
    def test_check_update_still_waiting(self, get_us_mock, log_mock):
        mock_update_service = mock.Mock()
        get_us_mock.return_value = mock_update_service
        self._generate_new_driver_internal_info(
            ['bios'], add_wait=True, wait=600)

        _, interface = self._test__check_node_redfish_firmware_update()
        debug_calls = [
            mock.call('Continuing to wait after firmware update '
                      '%(firmware_image)s on node %(node)s. '
                      'Elapsed time: %(seconds)s seconds',
                      {'firmware_image': 'https://bios/v1.0.1',
                       'node': self.node.uuid, 'seconds': 60})]
        log_mock.debug.assert_has_calls(debug_calls)
        interface._continue_updates.assert_not_called()

    @mock.patch.object(redfish_fw, 'LOG', autospec=True)
    @mock.patch.object(redfish_utils, 'get_update_service', autospec=True)
    @mock.patch.object(redfish_utils, 'get_task_monitor', autospec=True)
    def test_check_update_task_monitor_not_found(self, tm_mock, get_us_mock,
                                                 log_mock):
        tm_mock.side_effect = exception.RedfishError()
        self._generate_new_driver_internal_info(['bios'])

        task, interface = self._test__check_node_redfish_firmware_update()
        warning_calls = [
            mock.call('Firmware update completed for node %(node)s, '
                      'firmware %(firmware_image)s, but success of the '
                      'update is unknown.  Assuming update was successful.',
                      {'node': self.node.uuid,
                       'firmware_image': 'https://bios/v1.0.1'})]

        log_mock.warning.assert_has_calls(warning_calls)
        interface._continue_updates.assert_called_once_with(
            task, get_us_mock.return_value,
            [{'component': 'bios', 'url': 'https://bios/v1.0.1',
              'task_monitor': '/task/2'}]
        )

    @mock.patch.object(redfish_fw, 'LOG', autospec=True)
    @mock.patch.object(redfish_utils, 'get_update_service', autospec=True)
    @mock.patch.object(redfish_utils, 'get_task_monitor', autospec=True)
    def test__check_update_in_progress(self, tm_mock, get_us_mock, log_mock):
        tm_mock.return_value.is_processing = True
        self._generate_new_driver_internal_info(['bmc'])

        _, interface = self._test__check_node_redfish_firmware_update()
        debug_calls = [
            mock.call('Firmware update in progress for node %(node)s, '
                      'firmware %(firmware_image)s.',
                      {'node': self.node.uuid,
                       'firmware_image': 'https://bmc/v1.0.1'})]

        log_mock.debug.assert_has_calls(debug_calls)

        interface._continue_updates.assert_not_called()

    @mock.patch.object(redfish_fw, 'LOG', autospec=True)
    @mock.patch.object(redfish_utils, 'get_update_service', autospec=True)
    @mock.patch.object(redfish_utils, 'get_task_monitor', autospec=True)
    def test__check_update_task_state(self, tm_mock, get_us_mock, log_mock):
        """Test task with is_processing=False but still in active state.

        Some BMCs (particularly HPE iLO) may return is_processing=False
        while the task is still in RUNNING, STARTING, or PENDING state.
        The update should continue polling and not be treated as complete.
        """
        self._generate_new_driver_internal_info(['bmc'])

        # Test each of the three active states
        for task_state in [sushy.TASK_STATE_RUNNING,
                          sushy.TASK_STATE_STARTING,
                          sushy.TASK_STATE_PENDING]:
            log_mock.reset_mock()

            tm_mock.return_value.is_processing = False
            mock_task = tm_mock.return_value.get_task.return_value
            mock_task.task_state = task_state
            mock_task.task_status = sushy.HEALTH_OK

            _, interface = self._test__check_node_redfish_firmware_update()

            # Verify the new debug log message
            debug_calls = [
                mock.call('Firmware update task for node %(node)s is in '
                          '%(state)s state. Continuing to poll.',
                          {'node': self.node.uuid, 'state': task_state})]

            log_mock.debug.assert_has_calls(debug_calls)
            interface._continue_updates.assert_not_called()

    @mock.patch.object(manager_utils, 'cleaning_error_handler', autospec=True)
    @mock.patch.object(redfish_utils, 'get_update_service', autospec=True)
    @mock.patch.object(redfish_utils, 'get_task_monitor', autospec=True)
    def test__check_node_firmware_update_fail(self, tm_mock, get_us_mock,
                                              cleaning_error_handler_mock):
        mock_sushy_task = mock.Mock()
        mock_sushy_task.task_state = 'exception'
        mock_message_unparsed = mock.Mock()
        mock_message_unparsed.message = None
        message_mock = mock.Mock()
        message_mock.message = 'Firmware upgrade failed'
        messages = mock.MagicMock(return_value=[[mock_message_unparsed],
                                                [message_mock],
                                                [message_mock]])
        mock_sushy_task.messages = messages
        mock_task_monitor = mock.Mock()
        mock_task_monitor.is_processing = False
        mock_task_monitor.get_task.return_value = mock_sushy_task
        tm_mock.return_value = mock_task_monitor
        self._generate_new_driver_internal_info(['bmc'])

        task, interface = self._test__check_node_redfish_firmware_update()

        task.upgrade_lock.assert_called_once_with()
        cleaning_error_handler_mock.assert_called_once()
        interface._continue_updates.assert_not_called()

    @mock.patch.object(manager_utils, 'servicing_error_handler',
                       autospec=True)
    @mock.patch.object(redfish_utils, 'get_update_service', autospec=True)
    @mock.patch.object(redfish_utils, 'get_task_monitor', autospec=True)
    def test__check_node_firmware_update_fail_servicing(
            self, tm_mock,
            get_us_mock,
            servicing_error_handler_mock):

        mock_sushy_task = mock.Mock()
        mock_sushy_task.task_state = 'exception'
        mock_message_unparsed = mock.Mock()
        mock_message_unparsed.message = None
        message_mock = mock.Mock()
        message_mock.message = 'Firmware upgrade failed'
        messages = mock.MagicMock(return_value=[[mock_message_unparsed],
                                                [message_mock],
                                                [message_mock]])
        mock_sushy_task.messages = messages
        mock_task_monitor = mock.Mock()
        mock_task_monitor.is_processing = False
        mock_task_monitor.get_task.return_value = mock_sushy_task
        tm_mock.return_value = mock_task_monitor
        self._generate_new_driver_internal_info_service(['bmc'])

        task, interface = self._test__check_node_redfish_firmware_update()

        task.upgrade_lock.assert_called_once_with()
        servicing_error_handler_mock.assert_called_once()
        interface._continue_updates.assert_not_called()

    @mock.patch.object(redfish_fw.RedfishFirmware,
                       '_handle_bmc_update_completion', autospec=True)
    @mock.patch.object(redfish_fw, 'LOG', autospec=True)
    @mock.patch.object(redfish_utils, 'get_update_service', autospec=True)
    @mock.patch.object(redfish_utils, 'get_task_monitor', autospec=True)
    def test__check_node_firmware_update_done(self, tm_mock, get_us_mock,
                                              log_mock,
                                              bmc_completion_mock):
        task_mock = mock.Mock()
        task_mock.task_state = sushy.TASK_STATE_COMPLETED
        task_mock.task_status = sushy.HEALTH_OK
        message_mock = mock.Mock()
        message_mock.message = 'Firmware update done'
        task_mock.messages = [message_mock]
        mock_task_monitor = mock.Mock()
        mock_task_monitor.is_processing = False
        mock_task_monitor.get_task.return_value = task_mock
        tm_mock.return_value = mock_task_monitor
        self._generate_new_driver_internal_info(['bmc'])

        task, interface = self._test__check_node_redfish_firmware_update()
        task.upgrade_lock.assert_called_once_with()
        info_calls = [
            mock.call('Firmware update task completed for node %(node)s, '
                      'firmware %(firmware_image)s: %(messages)s.',
                      {'node': self.node.uuid,
                       'firmware_image': 'https://bmc/v1.0.1',
                       'messages': 'Firmware update done'})]

        log_mock.info.assert_has_calls(info_calls)
        # NOTE(iurygregory): _validate_resources_stability is now called
        # in _continue_updates before power operations, not in
        # _handle_task_completion

        # BMC updates now go through _handle_bmc_update_completion
        bmc_completion_mock.assert_called_once_with(
            interface, task, get_us_mock.return_value,
            [{'component': 'bmc', 'url': 'https://bmc/v1.0.1',
              'task_monitor': '/task/1'}],
            {'component': 'bmc', 'url': 'https://bmc/v1.0.1',
             'task_monitor': '/task/1'}
        )

    @mock.patch.object(firmware_utils, 'download_to_temp', autospec=True)
    @mock.patch.object(firmware_utils, 'stage', autospec=True)
    def test__stage_firmware_file_https(self, stage_mock, dwl_tmp_mock):
        CONF.set_override('firmware_source', 'local', 'redfish')
        firmware_update = {'url': 'https://test1', 'component': 'bmc'}
        node = mock.Mock()
        dwl_tmp_mock.return_value = '/tmp/test1'
        stage_mock.return_value = ('http://staged/test1', 'http')

        firmware = redfish_fw.RedfishFirmware()

        staged_url, needs_cleanup = firmware._stage_firmware_file(
            node, firmware_update)

        self.assertEqual(staged_url, 'http://staged/test1')
        self.assertEqual(needs_cleanup, 'http')
        dwl_tmp_mock.assert_called_with(node, 'https://test1')
        stage_mock.assert_called_with(node, 'local', '/tmp/test1')

    @mock.patch.object(firmware_utils, 'download_to_temp', autospec=True)
    @mock.patch.object(firmware_utils, 'stage', autospec=True)
    @mock.patch.object(firmware_utils, 'get_swift_temp_url', autospec=True)
    def test__stage_firmware_file_swift(
            self, get_swift_tmp_url_mock, stage_mock, dwl_tmp_mock):
        CONF.set_override('firmware_source', 'swift', 'redfish')
        firmware_update = {'url': 'swift://container/bios.exe',
                           'component': 'bios'}
        node = mock.Mock()
        get_swift_tmp_url_mock.return_value = 'http://temp'

        firmware = redfish_fw.RedfishFirmware()

        staged_url, needs_cleanup = firmware._stage_firmware_file(
            node, firmware_update)

        self.assertEqual(staged_url, 'http://temp')
        self.assertIsNone(needs_cleanup)
        dwl_tmp_mock.assert_not_called()
        stage_mock.assert_not_called()

    @mock.patch.object(firmware_utils, 'cleanup', autospec=True)
    @mock.patch.object(firmware_utils, 'download_to_temp', autospec=True)
    @mock.patch.object(firmware_utils, 'stage', autospec=True)
    def test__stage_firmware_file_error(self, stage_mock, dwl_tmp_mock,
                                        cleanup_mock):
        CONF.set_override('firmware_source', 'local', 'redfish')
        node = mock.Mock()
        firmware_update = {'url': 'https://test1', 'component': 'bmc'}
        dwl_tmp_mock.return_value = '/tmp/test1'
        stage_mock.side_effect = exception.IronicException

        firmware = redfish_fw.RedfishFirmware()
        self.assertRaises(exception.IronicException,
                          firmware._stage_firmware_file, node,
                          firmware_update)
        dwl_tmp_mock.assert_called_with(node, 'https://test1')
        stage_mock.assert_called_with(node, 'local', '/tmp/test1')
        cleanup_mock.assert_called_with(node)

    def _test_continue_updates(self):

        update_service_mock = mock.Mock()
        firmware = redfish_fw.RedfishFirmware()

        updates = self.node.driver_internal_info.get('redfish_fw_updates')

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            firmware._continue_updates(
                task,
                update_service_mock,
                updates
            )
            return task

    @mock.patch.object(redfish_fw, 'LOG', autospec=True)
    def test_continue_update_waitting(self, log_mock):
        self._generate_new_driver_internal_info(['bmc', 'bios'],
                                                add_wait=True, wait=120)
        self._test_continue_updates()
        debug_call = [
            mock.call('Waiting at %(time)s for %(seconds)s seconds '
                      'after %(component)s firmware update %(url)s '
                      'on node %(node)s',
                      {'time': mock.ANY, 'seconds': 120,
                       'component': 'bmc', 'url': 'https://bmc/v1.0.1',
                       'node': self.node.uuid})
        ]
        log_mock.debug.assert_has_calls(debug_call)

    @mock.patch.object(redfish_fw.RedfishFirmware,
                       '_validate_resources_stability', autospec=True)
    @mock.patch.object(redfish_fw, 'LOG', autospec=True)
    @mock.patch.object(manager_utils, 'notify_conductor_resume_clean',
                       autospec=True)
    def test_continue_updates_last(self, cond_resume_clean_mock, log_mock,
                                   validate_mock):
        self._generate_new_driver_internal_info(['bmc'])
        task = self._test_continue_updates()

        cond_resume_clean_mock.assert_called_once_with(task)
        # Verify BMC validation was called before resuming conductor
        validate_mock.assert_called_once()

        info_call = [
            mock.call('Firmware updates completed for node %(node)s',
                      {'node': self.node.uuid})
        ]
        log_mock.info.assert_has_calls(info_call)

    @mock.patch.object(redfish_fw.RedfishFirmware,
                       '_validate_resources_stability', autospec=True)
    @mock.patch.object(redfish_fw, 'LOG', autospec=True)
    @mock.patch.object(manager_utils, 'notify_conductor_resume_service',
                       autospec=True)
    def test_continue_updates_last_service(self, cond_resume_service_mock,
                                           log_mock, validate_mock):
        self._generate_new_driver_internal_info_service(['bmc'])
        task = self._test_continue_updates()

        cond_resume_service_mock.assert_called_once_with(task)
        # Verify BMC validation was called before resuming conductor
        validate_mock.assert_called_once()

        info_call = [
            mock.call('Firmware updates completed for node %(node)s',
                      {'node': self.node.uuid})
        ]
        log_mock.info.assert_has_calls(info_call)

    @mock.patch.object(redfish_fw.RedfishFirmware,
                       '_validate_resources_stability', autospec=True)
    @mock.patch.object(redfish_fw, 'LOG', autospec=True)
    @mock.patch.object(manager_utils, 'node_power_action', autospec=True)
    @mock.patch.object(redfish_utils, 'get_system_collection', autospec=True)
    def test_continue_updates_more_updates(self, get_system_collection_mock,
                                           node_power_action_mock,
                                           log_mock,
                                           validate_mock):
        cfg.CONF.set_override('firmware_update_wait_unresponsive_bmc', 0,
                              'redfish')
        self._generate_new_driver_internal_info(['bmc', 'bios'])

        task_monitor_mock = mock.Mock()
        task_monitor_mock.task_monitor_uri = '/task/2'
        update_service_mock = mock.Mock()
        update_service_mock.simple_update.return_value = task_monitor_mock

        firmware = redfish_fw.RedfishFirmware()
        updates = self.node.driver_internal_info.get('redfish_fw_updates')

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            task.node.save = mock.Mock()

            firmware._continue_updates(task, update_service_mock, updates)

            debug_calls = [
                mock.call('Applying new firmware %(url)s for '
                          '%(component)s on node %(node_uuid)s',
                          {'url': 'https://bios/v1.0.1', 'component': 'bios',
                           'node_uuid': self.node.uuid})
            ]
            log_mock.debug.assert_has_calls(debug_calls)
            self.assertEqual(
                [{'component': 'bios', 'url': 'https://bios/v1.0.1',
                  'task_monitor': '/task/2', 'power_timeout': 300}],
                task.node.driver_internal_info['redfish_fw_updates'])
            update_service_mock.simple_update.assert_called_once_with(
                'https://bios/v1.0.1')
            # NOTE(iurygregory): node.save() is called twice:
            # 1. Inside _execute_firmware_update via setup methods
            # 2. In _continue_updates after _execute_firmware_update returns
            self.assertEqual(task.node.save.call_count, 2)
            # Verify BMC validation was called before continuing to next update
            validate_mock.assert_called_once_with(firmware, task.node)
            node_power_action_mock.assert_called_once_with(task, states.REBOOT,
                                                           300)

    @mock.patch.object(redfish_utils, 'get_system', autospec=True)
    @mock.patch.object(redfish_utils, 'get_system_collection', autospec=True)
    @mock.patch.object(time, 'sleep', lambda seconds: None)
    def test__execute_firmware_update_no_targets(self,
                                                 get_system_collection_mock,
                                                 system_mock):
        self._generate_new_driver_internal_info(['bios'])
        with open('ironic/tests/json_samples/'
                  'systems_collection_single.json') as f:
            response_obj = json.load(f)
        system_collection_mock = mock.MagicMock()
        system_collection_mock.get_members.return_value = response_obj[
            'Members']
        get_system_collection_mock.return_value = system_collection_mock

        task_monitor_mock = mock.Mock()
        task_monitor_mock.task_monitor_uri = '/task/2'
        update_service_mock = mock.Mock()
        update_service_mock.simple_update.return_value = task_monitor_mock
        firmware = redfish_fw.RedfishFirmware()

        settings = [{'component': 'bios', 'url': 'https://bios/v1.0.1'}]
        firmware._execute_firmware_update(self.node, update_service_mock,
                                          settings)
        update_service_mock.simple_update.assert_called_once_with(
            'https://bios/v1.0.1')

    @mock.patch.object(redfish_utils, 'get_system', autospec=True)
    @mock.patch.object(redfish_utils, 'get_system_collection', autospec=True)
    @mock.patch.object(time, 'sleep', lambda seconds: None)
    def test__execute_firmware_update_targets(self,
                                              get_system_collection_mock,
                                              system_mock):
        self._generate_new_driver_internal_info(['bios'])
        with open('ironic/tests/json_samples/'
                  'systems_collection_dual.json') as f:
            response_obj = json.load(f)
        system_collection_mock = mock.MagicMock()
        system_collection_mock.members_identities = response_obj[
            'Members']
        get_system_collection_mock.return_value = system_collection_mock

        task_monitor_mock = mock.Mock()
        task_monitor_mock.task_monitor_uri = '/task/2'
        update_service_mock = mock.Mock()
        update_service_mock.simple_update.return_value = task_monitor_mock
        firmware = redfish_fw.RedfishFirmware()

        settings = [{'component': 'bios', 'url': 'https://bios/v1.0.1'}]
        firmware._execute_firmware_update(self.node, update_service_mock,
                                          settings)
        update_service_mock.simple_update.assert_called_once_with(
            'https://bios/v1.0.1', targets=[mock.ANY])

    @mock.patch.object(deploy_utils, 'set_async_step_flags', autospec=True)
    @mock.patch.object(redfish_utils, 'get_manager', autospec=True)
    @mock.patch.object(redfish_utils, 'get_system', autospec=True)
    @mock.patch.object(redfish_utils, 'get_system_collection', autospec=True)
    def test__execute_firmware_update_unresponsive_bmc(self,
                                                       get_sys_collec_mock,
                                                       system_mock,
                                                       manager_mock,
                                                       set_async_mock):
        cfg.CONF.set_override('firmware_update_wait_unresponsive_bmc', 1,
                              'redfish')
        self._generate_new_driver_internal_info(['bmc'])
        with open(
            'ironic/tests/json_samples/systems_collection_single.json'
        ) as f:
            resp_obj = json.load(f)
        system_collection_mock = mock.MagicMock()
        system_collection_mock.get_members.return_value = resp_obj['Members']
        get_sys_collec_mock.return_value = system_collection_mock

        # Mock BMC version reading for setup
        mock_manager = mock.Mock()
        mock_manager.firmware_version = '1.0.0'
        manager_mock.return_value = mock_manager

        task_monitor_mock = mock.Mock()
        task_monitor_mock.task_monitor_uri = '/task/2'
        update_service_mock = mock.Mock()
        update_service_mock.simple_update.return_value = task_monitor_mock
        firmware = redfish_fw.RedfishFirmware()
        settings = [{'component': 'bmc', 'url': 'https://bmc/v1.2.3'}]
        firmware._execute_firmware_update(self.node, update_service_mock,
                                          settings)
        update_service_mock.simple_update.assert_called_once_with(
            'https://bmc/v1.2.3')
        # Verify BMC monitoring setup was called (internally by _execute)
        set_async_mock.assert_called_once_with(
            self.node, reboot=False, polling=True)
    @mock.patch.object(deploy_utils, 'set_async_step_flags', autospec=True)
    @mock.patch.object(redfish_utils, 'get_manager', autospec=True)
    @mock.patch.object(redfish_utils, 'get_system', autospec=True)
    @mock.patch.object(redfish_utils, 'get_system_collection', autospec=True)
    def test__execute_firmware_update_unresponsive_bmc_node_override(
            self, get_sys_collec_mock, system_mock, manager_mock,
            set_async_mock):
        self._generate_new_driver_internal_info(['bmc'])
        # Set a specific value for firmware_update_unresponsive_bmc_wait for
        # the node
        with mock.patch('time.sleep', lambda x: None):
            d_info = self.node.driver_info.copy()
            d_info['firmware_update_unresponsive_bmc_wait'] = 1
            self.node.driver_info = d_info
            self.node.save()
        self.assertNotEqual(
            CONF.redfish.firmware_update_wait_unresponsive_bmc,
            self.node.driver_info.get('firmware_update_unresponsive_bmc_wait')
        )
        with open(
            'ironic/tests/json_samples/systems_collection_single.json'
        ) as f:
            resp_obj = json.load(f)
        system_collection_mock = mock.MagicMock()
        system_collection_mock.get_members.return_value = resp_obj['Members']
        get_sys_collec_mock.return_value = system_collection_mock

        # Mock BMC version reading for setup
        mock_manager = mock.Mock()
        mock_manager.firmware_version = '1.0.0'
        manager_mock.return_value = mock_manager

        task_monitor_mock = mock.Mock()
        task_monitor_mock.task_monitor_uri = '/task/2'
        update_service_mock = mock.Mock()
        update_service_mock.simple_update.return_value = task_monitor_mock
        firmware = redfish_fw.RedfishFirmware()
        settings = [{'component': 'bmc', 'url': 'https://bmc/v1.2.3'}]
        firmware._execute_firmware_update(self.node, update_service_mock,
                                          settings)
        update_service_mock.simple_update.assert_called_once_with(
            'https://bmc/v1.2.3')
        # Verify BMC monitoring setup was called (internally by _execute)
        set_async_mock.assert_called_once_with(
            self.node, reboot=False, polling=True)

    def test__validate_resources_stability_success(self):
        """Test successful BMC resource validation with consecutive success."""
        firmware = redfish_fw.RedfishFirmware()

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            with mock.patch.object(redfish_utils, 'get_system',
                                   autospec=True) as system_mock, \
                 mock.patch.object(redfish_utils, 'get_manager',
                                   autospec=True) as manager_mock, \
                 mock.patch.object(redfish_utils, 'get_chassis',
                                   autospec=True) as chassis_mock, \
                 mock.patch.object(time, 'time', autospec=True) as time_mock, \
                 mock.patch.object(time, 'sleep',
                                   autospec=True) as sleep_mock:

                # Mock successful resource responses
                system_mock.return_value = mock.Mock()
                manager_mock.return_value = mock.Mock()
                net_adapters = chassis_mock.return_value.network_adapters
                net_adapters.get_members.return_value = []

                # Mock time progression to simulate consecutive successes
                time_mock.side_effect = [0, 1, 2, 3]  # 3 successful attempts

                # Should complete successfully after 3 consecutive successes
                firmware._validate_resources_stability(task.node)

                # Verify all resources were checked 3 times (required success)
                self.assertEqual(system_mock.call_count, 3)
                self.assertEqual(manager_mock.call_count, 3)
                self.assertEqual(chassis_mock.call_count, 3)

                # Verify sleep was called between validation attempts
                expected_calls = [mock.call(
                    CONF.redfish.firmware_update_validation_interval)] * 2
                sleep_mock.assert_has_calls(expected_calls)

    def test__validate_resources_stability_timeout(self):
        """Test BMC resource validation timeout when not achieved."""
        firmware = redfish_fw.RedfishFirmware()

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            with mock.patch.object(redfish_utils, 'get_system',
                                   autospec=True) as system_mock, \
                 mock.patch.object(redfish_utils, 'get_manager',
                                   autospec=True), \
                 mock.patch.object(time, 'time', autospec=True) as time_mock, \
                 mock.patch.object(time, 'sleep', autospec=True):

                # Mock system always failing
                system_mock.side_effect = exception.RedfishConnectionError(
                    'timeout')

                # Mock time progression to exceed timeout
                time_mock.side_effect = [0, 350]  # Exceeds 300 second timeout

                # Should raise RedfishError due to timeout
                self.assertRaises(exception.RedfishError,
                                  firmware._validate_resources_stability,
                                  task.node)

    @mock.patch.object(redfish_fw, 'LOG', autospec=True)
    def test__validate_resources_stability_intermittent_failures(
            self, mock_log):
        """Test BMC resource validation with intermittent failures."""
        cfg.CONF.set_override('firmware_update_required_successes', 3,
                              'redfish')
        cfg.CONF.set_override('firmware_update_validation_interval', 10,
                              'redfish')

        firmware = redfish_fw.RedfishFirmware()

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            with mock.patch.object(redfish_utils, 'get_system',
                                   autospec=True) as system_mock, \
                 mock.patch.object(redfish_utils, 'get_manager',
                                   autospec=True) as manager_mock, \
                 mock.patch.object(redfish_utils, 'get_chassis',
                                   autospec=True) as chassis_mock, \
                 mock.patch.object(time, 'time', autospec=True) as time_mock, \
                 mock.patch.object(time, 'sleep', autospec=True):

                # Mock intermittent failures: success, success, fail,
                # success, success, success
                # When system_mock raises exception, other calls are not made
                call_count = 0

                def system_side_effect(*args):
                    nonlocal call_count
                    call_count += 1
                    if call_count == 3:  # Third call fails
                        raise exception.RedfishConnectionError('error')
                    return mock.Mock()

                system_mock.side_effect = system_side_effect
                manager_mock.return_value = mock.Mock()
                net_adapters = chassis_mock.return_value.network_adapters
                net_adapters.get_members.return_value = []

                # Mock time progression (6 attempts total)
                time_mock.side_effect = [0, 10, 20, 30, 40, 50, 60]

                # Should eventually succeed after counter reset
                firmware._validate_resources_stability(task.node)

                # Verify all 6 attempts were made for system
                self.assertEqual(system_mock.call_count, 6)
                # Manager and chassis called only 5 times (not on failed)
                self.assertEqual(manager_mock.call_count, 5)
                self.assertEqual(chassis_mock.call_count, 5)

                # Verify verbose logging about BMC recovery was called
                expected_log_call = mock.call(
                    'BMC resource validation failed for node %(node)s: '
                    '%(error)s. This may indicate the BMC is still '
                    'restarting or recovering from firmware update.',
                    {'node': task.node.uuid, 'error': mock.ANY})
                mock_log.debug.assert_has_calls([expected_log_call])

    def test__validate_resources_stability_manager_failure(self):
        """Test BMC resource validation when Manager resource fails."""
        firmware = redfish_fw.RedfishFirmware()

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            with mock.patch.object(redfish_utils, 'get_system',
                                   autospec=True) as system_mock, \
                 mock.patch.object(redfish_utils, 'get_manager',
                                   autospec=True) as manager_mock, \
                 mock.patch.object(time, 'time', autospec=True) as time_mock:

                # Mock system success, manager failure
                system_mock.return_value = mock.Mock()
                manager_mock.side_effect = exception.RedfishError(
                    'manager error')

                # Mock time progression to exceed timeout
                time_mock.side_effect = [0, 350]

                # Should raise RedfishError due to timeout
                self.assertRaises(exception.RedfishError,
                                  firmware._validate_resources_stability,
                                  task.node)

    def test__validate_resources_stability_network_adapters_failure(self):
        """Test validation when NetworkAdapters resource fails."""
        firmware = redfish_fw.RedfishFirmware()

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            with mock.patch.object(redfish_utils, 'get_system',
                                   autospec=True) as system_mock, \
                 mock.patch.object(redfish_utils, 'get_manager',
                                   autospec=True) as manager_mock, \
                 mock.patch.object(redfish_utils, 'get_chassis',
                                   autospec=True) as chassis_mock, \
                 mock.patch.object(time, 'time', autospec=True) as time_mock:

                # Mock system and manager success, NetworkAdapters failure
                system_mock.return_value = mock.Mock()
                manager_mock.return_value = mock.Mock()
                chassis_mock.side_effect = exception.RedfishError(
                    'chassis error')

                # Mock time progression to exceed timeout
                time_mock.side_effect = [0, 350]

                # Should raise RedfishError due to timeout
                self.assertRaises(exception.RedfishError,
                                  firmware._validate_resources_stability,
                                  task.node)

    def test__validate_resources_stability_custom_config(self):
        """Test BMC resource validation with custom configuration values."""
        cfg.CONF.set_override('firmware_update_required_successes', 5,
                              'redfish')
        cfg.CONF.set_override('firmware_update_validation_interval', 5,
                              'redfish')

        firmware = redfish_fw.RedfishFirmware()

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            with mock.patch.object(redfish_utils, 'get_system',
                                   autospec=True) as system_mock, \
                 mock.patch.object(redfish_utils, 'get_manager',
                                   autospec=True) as manager_mock, \
                 mock.patch.object(redfish_utils, 'get_chassis',
                                   autospec=True) as chassis_mock, \
                 mock.patch.object(time, 'time', autospec=True) as time_mock, \
                 mock.patch.object(time, 'sleep',
                                   autospec=True) as sleep_mock:

                # Mock successful resource responses
                system_mock.return_value = mock.Mock()
                manager_mock.return_value = mock.Mock()
                net_adapters = chassis_mock.return_value.network_adapters
                net_adapters.get_members.return_value = []

                # Mock time progression (5 successful attempts)
                time_mock.side_effect = [0, 5, 10, 15, 20, 25]

                # Should complete successfully after 5 consecutive successes
                firmware._validate_resources_stability(task.node)

                # Verify all resources checked 5 times (custom required)
                self.assertEqual(system_mock.call_count, 5)
                self.assertEqual(manager_mock.call_count, 5)
                self.assertEqual(chassis_mock.call_count, 5)

                # Verify sleep was called with custom interval
                expected_calls = [mock.call(5)] * 4  # 4 sleeps between 5
                sleep_mock.assert_has_calls(expected_calls)

    def test__validate_resources_stability_network_adapters_none(self):
        """Test validation succeeds when network_adapters is None."""
        firmware = redfish_fw.RedfishFirmware()

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            with mock.patch.object(redfish_utils, 'get_system',
                                   autospec=True) as system_mock, \
                 mock.patch.object(redfish_utils, 'get_manager',
                                   autospec=True) as manager_mock, \
                 mock.patch.object(redfish_utils, 'get_chassis',
                                   autospec=True) as chassis_mock, \
                 mock.patch.object(time, 'time', autospec=True) as time_mock, \
                 mock.patch.object(time, 'sleep', autospec=True):

                # Mock successful resource responses but network_adapters None
                system_mock.return_value = mock.Mock()
                manager_mock.return_value = mock.Mock()
                chassis_mock.return_value.network_adapters = None

                # Mock time progression to simulate consecutive successes
                time_mock.side_effect = [0, 1, 2, 3]

                # Should complete successfully (None network_adapters is OK)
                firmware._validate_resources_stability(task.node)

                # Verify all resources were checked 3 times
                self.assertEqual(system_mock.call_count, 3)
                self.assertEqual(manager_mock.call_count, 3)
                self.assertEqual(chassis_mock.call_count, 3)

    def test__validate_resources_stability_network_adapters_missing_attr(self):
        """Test validation succeeds when network_adapters is missing."""
        firmware = redfish_fw.RedfishFirmware()

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            with mock.patch.object(redfish_utils, 'get_system',
                                   autospec=True) as system_mock, \
                 mock.patch.object(redfish_utils, 'get_manager',
                                   autospec=True) as manager_mock, \
                 mock.patch.object(redfish_utils, 'get_chassis',
                                   autospec=True) as chassis_mock, \
                 mock.patch.object(time, 'time', autospec=True) as time_mock, \
                 mock.patch.object(time, 'sleep', autospec=True):

                # Mock successful resource responses
                system_mock.return_value = mock.Mock()
                manager_mock.return_value = mock.Mock()
                # network_adapters raises MissingAttributeError
                type(chassis_mock.return_value).network_adapters = (
                    mock.PropertyMock(
                        side_effect=sushy.exceptions.MissingAttributeError))

                # Mock time progression to simulate consecutive successes
                time_mock.side_effect = [0, 1, 2, 3]

                # Should complete successfully (missing network_adapters is OK)
                firmware._validate_resources_stability(task.node)

                # Verify all resources were checked 3 times
                self.assertEqual(system_mock.call_count, 3)
                self.assertEqual(manager_mock.call_count, 3)
                self.assertEqual(chassis_mock.call_count, 3)

    @mock.patch.object(redfish_fw, 'LOG', autospec=True)
    def test__validate_resources_stability_badrequest_error(self, mock_log):
        """Test BMC resource validation handles BadRequestError correctly."""
        firmware = redfish_fw.RedfishFirmware()

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            with mock.patch.object(redfish_utils, 'get_system',
                                   autospec=True) as system_mock, \
                 mock.patch.object(time, 'time', autospec=True) as time_mock, \
                 mock.patch.object(time, 'sleep', autospec=True):

                # Mock BadRequestError from sushy with proper arguments
                mock_response = mock.Mock()
                mock_response.status_code = 400
                system_mock.side_effect = sushy.exceptions.BadRequestError(
                    'http://test', mock_response, mock_response)

                # Mock time progression: start at 0, try once at 10, timeout
                # at 350, this allows at least one loop iteration to trigger
                # the exception
                time_mock.side_effect = [0, 10, 350]

                # Should raise RedfishError due to timeout
                self.assertRaises(exception.RedfishError,
                                  firmware._validate_resources_stability,
                                  task.node)

                # Verify verbose logging about BMC recovery was called
                expected_log_call = mock.call(
                    'BMC resource validation failed for node %(node)s: '
                    '%(error)s. This may indicate the BMC is still '
                    'restarting or recovering from firmware update.',
                    {'node': task.node.uuid, 'error': mock.ANY})
                mock_log.debug.assert_has_calls([expected_log_call])

    @mock.patch.object(redfish_utils, 'get_manager', autospec=True)
    @mock.patch.object(redfish_utils, 'get_system', autospec=True)
    @mock.patch.object(deploy_utils, 'set_async_step_flags', autospec=True)
    @mock.patch.object(redfish_fw.RedfishFirmware, '_execute_firmware_update',
                       autospec=True)
    @mock.patch.object(redfish_utils, 'get_update_service', autospec=True)
    def test_update_bmc_uses_configured_timeout(self, mock_get_update_service,
                                                mock_execute_fw_update,
                                                mock_set_async_flags,
                                                mock_get_system,
                                                mock_get_manager):
        """Test BMC firmware update sets up version checking."""
        settings = [{'component': 'bmc', 'url': 'http://bmc/v1.0.0'}]

        # Mock system
        mock_system = mock.Mock()
        mock_get_system.return_value = mock_system

        # Mock BMC version reading
        mock_manager = mock.Mock()
        mock_manager.firmware_version = '1.0.0'
        mock_get_manager.return_value = mock_manager

        # add task_monitor to the side effect
        mock_execute_fw_update.side_effect = self._mock_exc_fwup_side_effect

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.node.service_step = {'step': 'update',
                                      'interface': 'firmware'}
            result = task.driver.firmware.update(task, settings)

            # BMC uses version checking, not immediate reboot
            mock_set_async_flags.assert_called_once_with(
                task.node,
                reboot=False,
                polling=True
            )
            # Verify BMC version check tracking is set up
            info = task.node.driver_internal_info
            self.assertIn('bmc_fw_check_start_time', info)
            self.assertIn('bmc_fw_version_before_update', info)
            self.assertEqual(states.SERVICEWAIT, result)

    @mock.patch.object(redfish_utils, 'get_manager', autospec=True)
    @mock.patch.object(redfish_utils, 'get_system', autospec=True)
    @mock.patch.object(deploy_utils, 'set_async_step_flags', autospec=True)
    @mock.patch.object(redfish_fw.RedfishFirmware, '_execute_firmware_update',
                       autospec=True)
    @mock.patch.object(redfish_utils, 'get_update_service', autospec=True)
    def test_update_bmc_uses_bmc_constant(self, mock_get_update_service,
                                          mock_execute_fw_update,
                                          mock_set_async_flags,
                                          mock_get_system,
                                          mock_get_manager):
        """Test BMC firmware update detection works with BMC constant."""
        settings = [{'component': redfish_utils.BMC,
                     'url': 'http://bmc/v1.0.0'}]

        # Mock system
        mock_system = mock.Mock()
        mock_get_system.return_value = mock_system

        # Mock BMC version reading
        mock_manager = mock.Mock()
        mock_manager.firmware_version = '1.0.0'
        mock_get_manager.return_value = mock_manager

        # add task_monitor to the side effect
        mock_execute_fw_update.side_effect = self._mock_exc_fwup_side_effect

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.node.service_step = {'step': 'update',
                                      'interface': 'firmware'}
            result = task.driver.firmware.update(task, settings)

            # BMC uses version checking, not immediate reboot
            mock_set_async_flags.assert_called_once_with(
                task.node,
                reboot=False,
                polling=True
            )
            # Verify BMC version check tracking is set up
            info = task.node.driver_internal_info
            self.assertIn('bmc_fw_check_start_time', info)
            self.assertIn('bmc_fw_version_before_update', info)
            self.assertEqual(states.SERVICEWAIT, result)

    @mock.patch.object(deploy_utils, 'set_async_step_flags', autospec=True)
    @mock.patch.object(redfish_fw.RedfishFirmware, '_execute_firmware_update',
                       autospec=True)
    @mock.patch.object(redfish_utils, 'get_update_service', autospec=True)
    def test_update_non_bmc_uses_wait_parameter(self, mock_get_update_service,
                                                mock_execute_fw_update,
                                                mock_set_async_flags):
        """Test non-BMC firmware update with wait parameter (obsolete)."""
        # NOTE: This test is kept for historical reference but the wait
        # parameter on BIOS updates is no longer used as BIOS reboots
        # immediately when task starts rather than waiting
        settings = [{'component': 'bios', 'url': 'http://bios/v1.0.0',
                     'wait': 120}]

        # add task_monitor to the side effect
        mock_execute_fw_update.side_effect = self._mock_exc_fwup_side_effect

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.node.service_step = {'step': 'update',
                                      'interface': 'firmware'}
            result = task.driver.firmware.update(task, settings)

            # Verify reboot=True is set for BIOS
            mock_set_async_flags.assert_called_once_with(
                task.node,
                reboot=True,
                polling=True
            )
            self.assertEqual(states.SERVICEWAIT, result)

    @mock.patch.object(deploy_utils, 'set_async_step_flags', autospec=True)
    @mock.patch.object(redfish_fw.RedfishFirmware, '_execute_firmware_update',
                       autospec=True)
    @mock.patch.object(redfish_utils, 'get_update_service', autospec=True)
    def test_update_non_bmc_no_wait_parameter(self, mock_get_update_service,
                                              mock_execute_fw_update,
                                              mock_set_async_flags):
        """Test non-BMC firmware update without wait parameter."""
        settings = [{'component': 'bios', 'url': 'http://bios/v1.0.0'}]

        # add task_monitor to the side effect
        mock_execute_fw_update.side_effect = self._mock_exc_fwup_side_effect

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.node.service_step = {'step': 'update',
                                      'interface': 'firmware'}
            result = task.driver.firmware.update(task, settings)

            # Verify reboot=True is set for BIOS
            mock_set_async_flags.assert_called_once_with(
                task.node,
                reboot=True,
                polling=True
            )
            self.assertEqual(states.SERVICEWAIT, result)

    @mock.patch.object(deploy_utils, 'set_async_step_flags', autospec=True)
    @mock.patch.object(redfish_fw.RedfishFirmware, '_execute_firmware_update',
                       autospec=True)
    @mock.patch.object(redfish_utils, 'get_update_service', autospec=True)
    def test_update_mixed_components_with_bmc(self, mock_get_update_service,
                                              mock_execute_fw_update,
                                              mock_set_async_flags):
        """Test mixed component update with BIOS and BMC."""
        settings = [
            {'component': 'bios', 'url': 'http://bios/v1.0.0', 'wait': 120},
            {'component': 'bmc', 'url': 'http://bmc/v1.0.0', 'wait': 60}
        ]

        # add task_monitor to the side effect
        mock_execute_fw_update.side_effect = self._mock_exc_fwup_side_effect

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.node.service_step = {'step': 'update',
                                      'interface': 'firmware'}
            result = task.driver.firmware.update(task, settings)

            # First component is BIOS, so reboot=True
            mock_set_async_flags.assert_called_once_with(
                task.node,
                reboot=True,
                polling=True
            )
            self.assertEqual(states.SERVICEWAIT, result)

    @mock.patch.object(deploy_utils, 'set_async_step_flags', autospec=True)
    @mock.patch.object(redfish_fw.RedfishFirmware, '_execute_firmware_update',
                       autospec=True)
    @mock.patch.object(redfish_utils, 'get_update_service', autospec=True)
    def test_update_bmc_with_explicit_wait(self, mock_get_update_service,
                                           mock_execute_fw_update,
                                           mock_set_async_flags):
        """Test BMC update with explicit wait."""
        settings = [{'component': 'bmc', 'url': 'http://bmc/v1.0.0',
                     'wait': 90}]

        # add task_monitor to the side effect
        mock_execute_fw_update.side_effect = self._mock_exc_fwup_side_effect

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.node.service_step = {'step': 'update',
                                      'interface': 'firmware'}
            result = task.driver.firmware.update(task, settings)

            # BMC uses version checking, not immediate reboot
            mock_set_async_flags.assert_called_once_with(
                task.node,
                reboot=False,
                polling=True
            )
            # Verify wait time is stored
            info = task.node.driver_internal_info
            fw_updates = info['redfish_fw_updates']
            self.assertEqual(90, fw_updates[0]['wait'])
            self.assertEqual(states.SERVICEWAIT, result)

    @mock.patch.object(deploy_utils, 'set_async_step_flags', autospec=True)
    @mock.patch.object(redfish_utils, 'get_manager', autospec=True)
    @mock.patch.object(redfish_utils, 'get_system', autospec=True)
    @mock.patch.object(redfish_fw.RedfishFirmware, '_execute_firmware_update',
                       autospec=True)
    @mock.patch.object(redfish_utils, 'get_update_service', autospec=True)
    def test_update_bmc_no_immediate_reboot(self, mock_get_update_service,
                                            mock_execute_fw_update,
                                            mock_get_system,
                                            mock_get_manager,
                                            mock_set_async_flags):
        """Test BMC firmware update does not set immediate reboot."""
        settings = [{'component': 'bmc', 'url': 'http://bmc/v1.0.0'}]

        # Mock system
        mock_system = mock.Mock()
        mock_get_system.return_value = mock_system

        # Mock BMC version reading
        mock_manager = mock.Mock()
        mock_manager.firmware_version = '1.0.0'
        mock_get_manager.return_value = mock_manager

        # add task_monitor to the side effect
        mock_execute_fw_update.side_effect = self._mock_exc_fwup_side_effect

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.node.service_step = {'step': 'update',
                                      'interface': 'firmware'}
            result = task.driver.firmware.update(task, settings)

            # Verify reboot=False for BMC updates
            mock_set_async_flags.assert_called_once_with(
                task.node,
                reboot=False,
                polling=True
            )
            # Verify we return wait state to keep step active
            self.assertEqual(states.SERVICEWAIT, result)

            # Verify BMC version check tracking is set up
            info = task.node.driver_internal_info
            self.assertIn('bmc_fw_check_start_time', info)
            self.assertIn('bmc_fw_version_before_update', info)

    @mock.patch.object(deploy_utils, 'set_async_step_flags', autospec=True)
    @mock.patch.object(redfish_fw.RedfishFirmware, '_execute_firmware_update',
                       autospec=True)
    @mock.patch.object(redfish_utils, 'get_update_service', autospec=True)
    def test_update_nic_no_immediate_reboot(self, mock_get_update_service,
                                            mock_execute_fw_update,
                                            mock_set_async_flags):
        """Test NIC firmware update sets reboot flag, waits for task."""
        settings = [{'component': 'nic:BCM57414', 'url': 'http://nic/v1.0.0'}]

        # add task_monitor to the side effect
        mock_execute_fw_update.side_effect = self._mock_exc_fwup_side_effect

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.node.service_step = {'step': 'update',
                                      'interface': 'firmware'}
            result = task.driver.firmware.update(task, settings)

            # Verify reboot=True for NIC updates (reboot is conditional)
            mock_set_async_flags.assert_called_once_with(
                task.node,
                reboot=True,
                polling=True
            )
            # Verify we return wait state to keep step active
            self.assertEqual(states.SERVICEWAIT, result)

    @mock.patch.object(deploy_utils, 'set_async_step_flags', autospec=True)
    @mock.patch.object(redfish_fw.RedfishFirmware, '_execute_firmware_update',
                       autospec=True)
    @mock.patch.object(redfish_utils, 'get_update_service', autospec=True)
    def test_update_bios_sets_reboot_flag(self, mock_get_update_service,
                                          mock_execute_fw_update,
                                          mock_set_async_flags):
        """Test BIOS firmware update sets reboot flag."""
        settings = [{'component': 'bios', 'url': 'http://bios/v1.0.0'}]

        # add task_monitor to the side effect
        mock_execute_fw_update.side_effect = self._mock_exc_fwup_side_effect

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            # Set up node as if in service step
            task.node.service_step = {'step': 'update',
                                      'interface': 'firmware'}
            result = task.driver.firmware.update(task, settings)

            # Verify reboot=True for BIOS updates
            mock_set_async_flags.assert_called_once_with(
                task.node,
                reboot=True,
                polling=True
            )
            # Verify we return wait state to keep step active
            self.assertEqual(states.SERVICEWAIT, result)

    @mock.patch.object(timeutils, 'utcnow', autospec=True)
    @mock.patch.object(timeutils, 'parse_isotime', autospec=True)
    @mock.patch.object(redfish_fw.RedfishFirmware, '_continue_updates',
                       autospec=True)
    @mock.patch.object(deploy_utils, 'set_async_step_flags', autospec=True)
    @mock.patch.object(redfish_fw.RedfishFirmware,
                       '_get_current_bmc_version', autospec=True)
    @mock.patch.object(redfish_utils, 'get_update_service', autospec=True)
    def test_bmc_version_check_timeout_sets_reboot_flag(
            self, mock_get_update_service, mock_get_bmc_version,
            mock_set_async_flags, mock_continue_updates,
            mock_parse_isotime, mock_utcnow):
        """Test BMC version check timeout sets reboot request flag."""
        import datetime
        start_time = datetime.datetime(2025, 1, 1, 0, 0, 0,
                                       tzinfo=datetime.timezone.utc)
        current_time = start_time + datetime.timedelta(seconds=301)
        mock_parse_isotime.return_value = start_time
        mock_utcnow.return_value = current_time
        settings = [{'component': 'bmc', 'url': 'http://bmc/v1.0.0',
                     'wait': 300, 'task_monitor': '/tasks/1'}]

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            # Set up node with BMC version checking in progress
            task.node.set_driver_internal_info(
                'redfish_fw_updates', settings)
            task.node.set_driver_internal_info(
                'bmc_fw_check_start_time', '2025-01-01T00:00:00.000000')

            # Mock BMC is unresponsive
            mock_get_bmc_version.return_value = None

            # Call the BMC update completion handler
            firmware_interface = redfish_fw.RedfishFirmware()
            firmware_interface._handle_bmc_update_completion(
                task, mock_get_update_service.return_value,
                settings, settings[0])

            # Verify reboot flag is set
            info = task.node.driver_internal_info
            self.assertTrue(info.get('firmware_reboot_requested'))

            # Verify async flags updated with reboot=True
            mock_set_async_flags.assert_called_once_with(
                task.node,
                reboot=True,
                polling=True
            )

            # Verify _continue_updates was called
            mock_continue_updates.assert_called_once()

    @mock.patch.object(redfish_fw.RedfishFirmware, '_continue_updates',
                       autospec=True)
    @mock.patch.object(deploy_utils, 'set_async_step_flags', autospec=True)
    @mock.patch.object(redfish_fw.RedfishFirmware,
                       '_validate_resources_stability', autospec=True)
    @mock.patch.object(redfish_utils, 'get_update_service', autospec=True)
    @mock.patch.object(redfish_utils, 'get_task_monitor', autospec=True)
    def test_nic_completion_sets_reboot_flag(
            self, mock_get_task_monitor, mock_get_update_service,
            mock_validate_resources, mock_set_async_flags,
            mock_continue_updates):
        """Test NIC firmware task completion sets reboot request flag."""
        settings = [{'component': 'nic:BCM57414',
                     'url': 'http://nic/v1.0.0',
                     'task_monitor': '/tasks/1'}]

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            # Set up node with NIC update in progress
            # Set nic_needs_post_completion_reboot to simulate hardware
            # that started update immediately but needs reboot after completion
            settings[0]['nic_needs_post_completion_reboot'] = True
            task.node.set_driver_internal_info(
                'redfish_fw_updates', settings)

            # Mock task completion
            mock_task_monitor = mock.Mock()
            mock_task_monitor.is_processing = False
            mock_task = mock.Mock()
            mock_task.task_state = sushy.TASK_STATE_COMPLETED
            mock_task.task_status = sushy.HEALTH_OK
            mock_task.messages = []
            mock_task_monitor.get_task.return_value = mock_task
            mock_get_task_monitor.return_value = mock_task_monitor

            # Call the check method
            firmware_interface = redfish_fw.RedfishFirmware()
            firmware_interface._check_node_redfish_firmware_update(task)

            # Verify reboot flag is set
            info = task.node.driver_internal_info
            self.assertTrue(info.get('firmware_reboot_requested'))

            # Verify _continue_updates was called
            mock_continue_updates.assert_called_once()

    @mock.patch.object(redfish_fw.RedfishFirmware,
                       '_validate_resources_stability', autospec=True)
    @mock.patch.object(manager_utils, 'notify_conductor_resume_clean',
                       autospec=True)
    @mock.patch.object(manager_utils, 'node_power_action', autospec=True)
    @mock.patch.object(redfish_fw.RedfishFirmware, '_clear_updates',
                       autospec=True)
    @mock.patch.object(redfish_utils, 'get_update_service', autospec=True)
    def test_final_update_with_reboot_flag_triggers_reboot(
            self, mock_get_update_service, mock_clear_updates,
            mock_power_action, mock_resume_clean, validate_mock):
        """Test final firmware update with reboot flag triggers reboot."""
        settings = [{'component': 'bmc', 'url': 'http://bmc/v1.0.0',
                     'task_monitor': '/tasks/1'}]

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            # Set up node as if in cleaning
            task.node.clean_step = {'step': 'update', 'interface': 'firmware'}

            # Set up final update with reboot requested
            task.node.set_driver_internal_info(
                'redfish_fw_updates', settings)
            task.node.set_driver_internal_info(
                'firmware_reboot_requested', True)

            # Call _continue_updates with last firmware
            firmware_interface = redfish_fw.RedfishFirmware()
            firmware_interface._continue_updates(
                task, mock_get_update_service.return_value, settings)

            # Verify reboot was triggered
            mock_power_action.assert_called_once_with(task, states.REBOOT)

            # Verify BMC validation was called before resuming conductor
            validate_mock.assert_called_once()

            # Verify resume clean was called
            mock_resume_clean.assert_called_once_with(task)

    @mock.patch.object(redfish_fw.RedfishFirmware,
                       '_validate_resources_stability', autospec=True)
    @mock.patch.object(manager_utils, 'notify_conductor_resume_clean',
                       autospec=True)
    @mock.patch.object(manager_utils, 'node_power_action', autospec=True)
    @mock.patch.object(redfish_fw.RedfishFirmware, '_clear_updates',
                       autospec=True)
    @mock.patch.object(redfish_utils, 'get_update_service', autospec=True)
    def test_final_update_without_reboot_flag_no_reboot(
            self, mock_get_update_service, mock_clear_updates,
            mock_power_action, mock_resume_clean, validate_mock):
        """Test final firmware update without reboot flag skips reboot."""
        settings = [{'component': 'bmc', 'url': 'http://bmc/v1.0.0',
                     'task_monitor': '/tasks/1'}]

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            # Set up node as if in cleaning
            task.node.clean_step = {'step': 'update', 'interface': 'firmware'}

            # Set up final update WITHOUT reboot requested
            task.node.set_driver_internal_info(
                'redfish_fw_updates', settings)
            # Don't set firmware_reboot_requested

            # Call _continue_updates with last firmware
            firmware_interface = redfish_fw.RedfishFirmware()
            firmware_interface._continue_updates(
                task, mock_get_update_service.return_value, settings)

            # Verify reboot was NOT triggered
            mock_power_action.assert_not_called()

            # Verify BMC validation was called before resuming conductor
            validate_mock.assert_called_once()

            # Verify resume clean was still called
            mock_resume_clean.assert_called_once_with(task)

    @mock.patch.object(manager_utils, 'node_power_action', autospec=True)
    @mock.patch.object(redfish_utils, 'get_update_service', autospec=True)
    @mock.patch.object(redfish_utils, 'get_task_monitor', autospec=True)
    def test_bios_reboot_on_task_starting(
            self, mock_get_task_monitor, mock_get_update_service,
            mock_power_action):
        """Test BIOS update triggers reboot when task reaches STARTING."""
        settings = [{'component': 'bios', 'url': 'http://bios/v1.0.1',
                     'task_monitor': '/tasks/1'}]

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            # Set up node with BIOS update in progress
            task.node.set_driver_internal_info('redfish_fw_updates', settings)
            task.node.clean_step = {'step': 'update', 'interface': 'firmware'}

            # Mock task monitor to return is_processing=True
            mock_task_monitor = mock.Mock()
            mock_task_monitor.is_processing = True
            mock_get_task_monitor.return_value = mock_task_monitor

            # Mock the task state as STARTING
            mock_task = mock.Mock()
            mock_task.task_state = sushy.TASK_STATE_STARTING
            mock_task_monitor.get_task.return_value = mock_task

            # Call the check method
            firmware_interface = redfish_fw.RedfishFirmware()
            firmware_interface._check_node_redfish_firmware_update(task)

            # Verify reboot was triggered
            mock_power_action.assert_called_once_with(task, states.REBOOT, 0)

            # Verify the flag was set to prevent repeated reboots
            updated_settings = task.node.driver_internal_info[
                'redfish_fw_updates']
            self.assertTrue(updated_settings[0].get('bios_reboot_triggered'))

    @mock.patch.object(manager_utils, 'node_power_action', autospec=True)
    @mock.patch.object(redfish_utils, 'get_update_service', autospec=True)
    @mock.patch.object(redfish_utils, 'get_task_monitor', autospec=True)
    def test_bios_no_repeated_reboot_after_flag_set(
            self, mock_get_task_monitor, mock_get_update_service,
            mock_power_action):
        """Test BIOS update doesn't reboot again after flag is set."""
        settings = [{'component': 'bios', 'url': 'http://bios/v1.0.1',
                     'task_monitor': '/tasks/1',
                     'bios_reboot_triggered': True}]

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            # Set up node with BIOS update in progress and flag already set
            task.node.set_driver_internal_info('redfish_fw_updates', settings)
            task.node.clean_step = {'step': 'update', 'interface': 'firmware'}

            # Mock task monitor to return is_processing=True
            mock_task_monitor = mock.Mock()
            mock_task_monitor.is_processing = True
            mock_get_task_monitor.return_value = mock_task_monitor

            # Call the check method
            firmware_interface = redfish_fw.RedfishFirmware()
            firmware_interface._check_node_redfish_firmware_update(task)

            # Verify reboot was NOT triggered again
            mock_power_action.assert_not_called()

    @mock.patch.object(redfish_fw, 'LOG', autospec=True)
    @mock.patch.object(redfish_fw.RedfishFirmware, '_continue_updates',
                       autospec=True)
    @mock.patch.object(manager_utils, 'node_power_action', autospec=True)
    @mock.patch.object(redfish_utils, 'get_update_service', autospec=True)
    @mock.patch.object(redfish_utils, 'get_task_monitor', autospec=True)
    def test_bios_reboot_on_completion_without_prior_reboot(
            self, mock_get_task_monitor, mock_get_update_service,
            mock_power_action, mock_continue_updates, mock_log):
        """Test BIOS task completion triggers reboot when not triggered before.

        This test verifies the alternate path where a BIOS firmware update
        task completes very quickly (e.g., HPE iLO staging firmware) before
        Ironic can trigger a reboot during the STARTING state. In this case,
        when the task reaches COMPLETED state and bios_reboot_triggered is
        not set, we should:
        1. Trigger a reboot to apply the staged firmware
        2. NOT call _continue_updates (return early)
        3. Set the bios_reboot_triggered flag
        """
        settings = [{'component': 'bios', 'url': 'http://bios/v1.0.1',
                     'task_monitor': '/tasks/1'}]

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            # Set up node with BIOS update in progress
            # Note: bios_reboot_triggered is NOT set
            task.node.set_driver_internal_info('redfish_fw_updates', settings)
            task.node.clean_step = {'step': 'update', 'interface': 'firmware'}

            # Mock task monitor showing task is completed
            mock_task_monitor = mock.Mock()
            mock_task_monitor.is_processing = False
            mock_task = mock.Mock()
            mock_task.task_state = sushy.TASK_STATE_COMPLETED
            mock_task.task_status = sushy.HEALTH_OK
            mock_task.messages = []
            mock_task_monitor.get_task.return_value = mock_task
            mock_get_task_monitor.return_value = mock_task_monitor

            # Call the check method
            firmware_interface = redfish_fw.RedfishFirmware()
            firmware_interface._check_node_redfish_firmware_update(task)

            # Verify reboot WAS triggered
            mock_power_action.assert_called_once_with(task, states.REBOOT, 0)

            # Verify _continue_updates was NOT called (early return)
            mock_continue_updates.assert_not_called()

            # Verify the flag was set to prevent repeated reboots
            updated_settings = task.node.driver_internal_info[
                'redfish_fw_updates']
            self.assertTrue(updated_settings[0].get('bios_reboot_triggered'))

            # Verify LOG.info was called with the correct message
            mock_log.info.assert_any_call(
                'BIOS firmware update task completed for node '
                '%(node)s but reboot was not triggered yet. '
                'Triggering reboot now to apply staged firmware.',
                {'node': task.node.uuid})

    @mock.patch.object(redfish_fw, 'LOG', autospec=True)
    @mock.patch.object(redfish_fw.RedfishFirmware, '_continue_updates',
                       autospec=True)
    @mock.patch.object(manager_utils, 'node_power_action', autospec=True)
    @mock.patch.object(redfish_utils, 'get_update_service', autospec=True)
    @mock.patch.object(redfish_utils, 'get_task_monitor', autospec=True)
    def test_bios_continue_after_completion_with_prior_reboot(
            self, mock_get_task_monitor, mock_get_update_service,
            mock_power_action, mock_continue_updates, mock_log):
        """Test BIOS task completion continues when reboot already triggered.

        This test verifies the else path where a BIOS firmware update task
        completes and the reboot was already triggered (during STARTING state).
        In this case, when the task reaches COMPLETED state and
        bios_reboot_triggered is already set, we should:
        1. NOT trigger another reboot
        2. Call _continue_updates to proceed with next firmware
        3. Clean up the bios_reboot_triggered flag
        """
        settings = [{'component': 'bios', 'url': 'http://bios/v1.0.1',
                     'task_monitor': '/tasks/1',
                     'bios_reboot_triggered': True}]  # Flag already set

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            # Set up node with BIOS update in progress
            # Note: bios_reboot_triggered IS set (reboot already happened)
            task.node.set_driver_internal_info('redfish_fw_updates', settings)
            task.node.clean_step = {'step': 'update', 'interface': 'firmware'}

            # Mock task monitor showing task is completed
            mock_task_monitor = mock.Mock()
            mock_task_monitor.is_processing = False
            mock_task = mock.Mock()
            mock_task.task_state = sushy.TASK_STATE_COMPLETED
            mock_task.task_status = sushy.HEALTH_OK
            mock_task.messages = []
            mock_task_monitor.get_task.return_value = mock_task
            mock_get_task_monitor.return_value = mock_task_monitor

            # Call the check method
            firmware_interface = redfish_fw.RedfishFirmware()
            firmware_interface._check_node_redfish_firmware_update(task)

            # Verify reboot was NOT triggered (already happened)
            mock_power_action.assert_not_called()

            # Verify _continue_updates WAS called
            mock_continue_updates.assert_called_once_with(
                firmware_interface, task, mock_get_update_service.return_value,
                settings)

            # Verify the flag was cleaned up (popped from settings)
            updated_settings = task.node.driver_internal_info[
                'redfish_fw_updates']
            self.assertIsNone(updated_settings[0].get('bios_reboot_triggered'))

            # Verify LOG.info was called with the correct message
            mock_log.info.assert_any_call(
                'BIOS firmware update task completed for node '
                '%(node)s. System was already rebooted. '
                'Proceeding with continuation.',
                {'node': task.node.uuid})
