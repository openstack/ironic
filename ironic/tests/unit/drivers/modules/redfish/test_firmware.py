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

        log_mock.warning.assert_any_call(
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
                       '_validate_resources_stability', autospec=True)
    @mock.patch.object(redfish_fw, 'LOG', autospec=True)
    @mock.patch.object(redfish_utils, 'get_update_service', autospec=True)
    @mock.patch.object(redfish_utils, 'get_task_monitor', autospec=True)
    def test__check_node_firmware_update_done(self, tm_mock, get_us_mock,
                                              log_mock, validate_mock):
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
                      'firmware %(firmware_image)s: %(messages)s. '
                      'Starting BMC response validation.',
                      {'node': self.node.uuid,
                       'firmware_image': 'https://bmc/v1.0.1',
                       'messages': 'Firmware update done'})]

        log_mock.info.assert_has_calls(info_calls)
        validate_mock.assert_called_once()

        interface._continue_updates.assert_called_once_with(
            task, get_us_mock.return_value,
            [{'component': 'bmc', 'url': 'https://bmc/v1.0.1',
              'task_monitor': '/task/1'}]
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

    @mock.patch.object(redfish_fw, 'LOG', autospec=True)
    @mock.patch.object(manager_utils, 'notify_conductor_resume_clean',
                       autospec=True)
    def test_continue_updates_last(self, cond_resume_clean_mock, log_mock):
        self._generate_new_driver_internal_info(['bmc'])
        task = self._test_continue_updates()

        cond_resume_clean_mock.assert_called_once_with(task)

        info_call = [
            mock.call('Firmware updates completed for node %(node)s',
                      {'node': self.node.uuid})
        ]
        log_mock.info.assert_has_calls(info_call)

    @mock.patch.object(redfish_fw, 'LOG', autospec=True)
    @mock.patch.object(manager_utils, 'notify_conductor_resume_service',
                       autospec=True)
    def test_continue_updates_last_service(self, cond_resume_service_mock,
                                           log_mock):
        self._generate_new_driver_internal_info_service(['bmc'])
        task = self._test_continue_updates()

        cond_resume_service_mock.assert_called_once_with(task)

        info_call = [
            mock.call('Firmware updates completed for node %(node)s',
                      {'node': self.node.uuid})
        ]
        log_mock.info.assert_has_calls(info_call)

    @mock.patch.object(redfish_fw, 'LOG', autospec=True)
    @mock.patch.object(manager_utils, 'node_power_action', autospec=True)
    @mock.patch.object(redfish_utils, 'get_system_collection', autospec=True)
    def test_continue_updates_more_updates(self, get_system_collection_mock,
                                           node_power_action_mock,
                                           log_mock):
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
                  'task_monitor': '/task/2'}],
                task.node.driver_internal_info['redfish_fw_updates'])
            update_service_mock.simple_update.assert_called_once_with(
                'https://bios/v1.0.1')
            task.node.save.assert_called_once_with()
            node_power_action_mock.assert_called_once_with(task, states.REBOOT)

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

    @mock.patch.object(redfish_utils, 'get_system', autospec=True)
    @mock.patch.object(redfish_utils, 'get_system_collection', autospec=True)
    @mock.patch.object(time, 'sleep', autospec=True)
    def test__execute_firmware_update_unresponsive_bmc(self, sleep_mock,
                                                       get_sys_collec_mock,
                                                       system_mock):
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
        sleep_mock.assert_called_once_with(
            CONF.redfish.firmware_update_wait_unresponsive_bmc)

    @mock.patch.object(redfish_utils, 'get_system', autospec=True)
    @mock.patch.object(redfish_utils, 'get_system_collection', autospec=True)
    @mock.patch.object(time, 'sleep', autospec=True)
    def test__execute_firmware_update_unresponsive_bmc_node_override(
            self, sleep_mock, get_sys_collec_mock, system_mock):
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
        sleep_mock.assert_called_once_with(
            self.node.driver_info.get('firmware_update_unresponsive_bmc_wait')
        )

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

    def test__validate_resources_stability_intermittent_failures(self):
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

    def test__validate_resources_stability_badrequest_error(self):
        """Test BMC resource validation handles BadRequestError correctly."""
        firmware = redfish_fw.RedfishFirmware()

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            with mock.patch.object(redfish_utils, 'get_system',
                                   autospec=True) as system_mock, \
                 mock.patch.object(time, 'time', autospec=True) as time_mock:

                # Mock BadRequestError from sushy with proper arguments
                mock_response = mock.Mock()
                mock_response.status_code = 400
                system_mock.side_effect = sushy.exceptions.BadRequestError(
                    'http://test', mock_response, mock_response)

                # Mock time progression to exceed timeout
                time_mock.side_effect = [0, 350]

                # Should raise RedfishError due to timeout
                self.assertRaises(exception.RedfishError,
                                  firmware._validate_resources_stability,
                                  task.node)

    @mock.patch.object(time, 'sleep', lambda seconds: None)
    @mock.patch.object(deploy_utils, 'reboot_to_finish_step', autospec=True)
    @mock.patch.object(deploy_utils, 'set_async_step_flags', autospec=True)
    @mock.patch.object(redfish_fw.RedfishFirmware, '_execute_firmware_update',
                       autospec=True)
    @mock.patch.object(redfish_utils, 'get_update_service', autospec=True)
    def test_update_bmc_uses_configured_timeout(self, mock_get_update_service,
                                                mock_execute_fw_update,
                                                mock_set_async_flags,
                                                mock_reboot_to_finish):
        """Test BMC firmware update uses configured timeout."""
        settings = [{'component': 'bmc', 'url': 'http://bmc/v1.0.0'}]

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.driver.firmware.update(task, settings)

            # Verify configured timeout is used for BMC update
            mock_reboot_to_finish.assert_called_once_with(
                task, timeout=CONF.redfish.firmware_update_bmc_timeout,
                disable_ramdisk=True)

    @mock.patch.object(time, 'sleep', lambda seconds: None)
    @mock.patch.object(deploy_utils, 'reboot_to_finish_step', autospec=True)
    @mock.patch.object(deploy_utils, 'set_async_step_flags', autospec=True)
    @mock.patch.object(redfish_fw.RedfishFirmware, '_execute_firmware_update',
                       autospec=True)
    @mock.patch.object(redfish_utils, 'get_update_service', autospec=True)
    def test_update_bmc_uses_bmc_constant(self, mock_get_update_service,
                                          mock_execute_fw_update,
                                          mock_set_async_flags,
                                          mock_reboot_to_finish):
        """Test BMC firmware update detection works with BMC constant."""
        settings = [{'component': redfish_utils.BMC,
                     'url': 'http://bmc/v1.0.0'}]

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.driver.firmware.update(task, settings)

            # Verify configured timeout is used
            mock_reboot_to_finish.assert_called_once_with(
                task, timeout=CONF.redfish.firmware_update_bmc_timeout,
                disable_ramdisk=True)

    @mock.patch.object(time, 'sleep', lambda seconds: None)
    @mock.patch.object(deploy_utils, 'reboot_to_finish_step', autospec=True)
    @mock.patch.object(deploy_utils, 'set_async_step_flags', autospec=True)
    @mock.patch.object(redfish_fw.RedfishFirmware, '_execute_firmware_update',
                       autospec=True)
    @mock.patch.object(redfish_utils, 'get_update_service', autospec=True)
    def test_update_non_bmc_uses_wait_parameter(self, mock_get_update_service,
                                                mock_execute_fw_update,
                                                mock_set_async_flags,
                                                mock_reboot_to_finish):
        """Test non-BMC firmware update uses wait parameter."""
        settings = [{'component': 'bios', 'url': 'http://bios/v1.0.0',
                     'wait': 120}]

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.driver.firmware.update(task, settings)

            # Verify wait parameter is used for non-BMC update
            mock_reboot_to_finish.assert_called_once_with(
                task, timeout=120, disable_ramdisk=True)

    @mock.patch.object(time, 'sleep', lambda seconds: None)
    @mock.patch.object(deploy_utils, 'reboot_to_finish_step', autospec=True)
    @mock.patch.object(deploy_utils, 'set_async_step_flags', autospec=True)
    @mock.patch.object(redfish_fw.RedfishFirmware, '_execute_firmware_update',
                       autospec=True)
    @mock.patch.object(redfish_utils, 'get_update_service', autospec=True)
    def test_update_non_bmc_no_wait_parameter(self, mock_get_update_service,
                                              mock_execute_fw_update,
                                              mock_set_async_flags,
                                              mock_reboot_to_finish):
        """Test non-BMC firmware update without wait parameter uses None."""
        settings = [{'component': 'bios', 'url': 'http://bios/v1.0.0'}]

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.driver.firmware.update(task, settings)

            # Verify None timeout is used for non-BMC without wait parameter
            mock_reboot_to_finish.assert_called_once_with(
                task, timeout=None, disable_ramdisk=True)

    @mock.patch.object(time, 'sleep', lambda seconds: None)
    @mock.patch.object(deploy_utils, 'reboot_to_finish_step', autospec=True)
    @mock.patch.object(deploy_utils, 'set_async_step_flags', autospec=True)
    @mock.patch.object(redfish_fw.RedfishFirmware, '_execute_firmware_update',
                       autospec=True)
    @mock.patch.object(redfish_utils, 'get_update_service', autospec=True)
    def test_update_mixed_components_with_bmc(self, mock_get_update_service,
                                              mock_execute_fw_update,
                                              mock_set_async_flags,
                                              mock_reboot_to_finish):
        """Test mixed component update with BMC and explicit wait uses wait."""
        settings = [
            {'component': 'bios', 'url': 'http://bios/v1.0.0', 'wait': 120},
            {'component': 'bmc', 'url': 'http://bmc/v1.0.0', 'wait': 60}
        ]

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.driver.firmware.update(task, settings)

            # Verify explicit wait parameter takes precedence over BMC timeout
            mock_reboot_to_finish.assert_called_once_with(
                task, timeout=120,
                disable_ramdisk=True)

    @mock.patch.object(time, 'sleep', lambda seconds: None)
    @mock.patch.object(deploy_utils, 'reboot_to_finish_step', autospec=True)
    @mock.patch.object(deploy_utils, 'set_async_step_flags', autospec=True)
    @mock.patch.object(redfish_fw.RedfishFirmware, '_execute_firmware_update',
                       autospec=True)
    @mock.patch.object(redfish_utils, 'get_update_service', autospec=True)
    def test_update_bmc_with_explicit_wait(self, mock_get_update_service,
                                           mock_execute_fw_update,
                                           mock_set_async_flags,
                                           mock_reboot_to_finish):
        """Test BMC update with explicit wait uses wait, not BMC timeout."""
        settings = [{'component': 'bmc', 'url': 'http://bmc/v1.0.0',
                     'wait': 90}]

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.driver.firmware.update(task, settings)

            # Verify explicit wait parameter takes precedence over BMC timeout
            mock_reboot_to_finish.assert_called_once_with(
                task, timeout=90, disable_ramdisk=True)
