# -*- coding: utf-8 -*-
#
# Copyright 2014 Red Hat, Inc.
# All Rights Reserved.
# Copyright (c) 2017-2021 Dell Inc. or its subsidiaries.
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

"""
Test class for DRAC management interface
"""

import json
from unittest import mock

import sushy

import ironic.common.boot_devices
from ironic.common import exception
from ironic.common import molds
from ironic.common import states
from ironic.conductor import periodics
from ironic.conductor import task_manager
from ironic.conductor import utils as manager_utils
from ironic.drivers.modules import deploy_utils
from ironic.drivers.modules.drac import management as drac_mgmt
from ironic.drivers.modules.drac import utils as drac_utils
from ironic.drivers.modules.redfish import utils as redfish_utils
from ironic.tests.unit.drivers.modules.drac import utils as test_utils
from ironic.tests.unit.objects import utils as obj_utils


INFO_DICT = test_utils.INFO_DICT


class DracRedfishManagementTestCase(test_utils.BaseDracTest):

    def setUp(self):
        super(DracRedfishManagementTestCase, self).setUp()
        self.node = obj_utils.create_test_node(self.context,
                                               driver='idrac',
                                               driver_info=INFO_DICT)
        self.management = drac_mgmt.DracRedfishManagement()

        self.config(enabled_hardware_types=['idrac'],
                    enabled_power_interfaces=['idrac-redfish'],
                    enabled_management_interfaces=['idrac-redfish'])

    def test_export_configuration_name_missing(self):
        task = mock.Mock(node=self.node, context=self.context)
        self.assertRaises(exception.MissingParameterValue,
                          self.management.export_configuration, task, None)

    @mock.patch.object(redfish_utils, 'get_system', autospec=True)
    def test_export_configuration_export_failed(self, mock_get_system):
        task = mock.Mock(node=self.node, context=self.context)
        fake_manager_oem1 = mock.Mock()
        fake_manager_oem1.export_system_configuration = mock.Mock()
        fake_manager_oem1.export_system_configuration.status_code = 500
        fake_manager1 = mock.Mock()
        fake_manager1.get_oem_extension.return_value = fake_manager_oem1
        mock_get_system.return_value.managers = [fake_manager1]

        self.assertRaises(exception.DracOperationError,
                          self.management.export_configuration, task, 'edge')

    @mock.patch.object(drac_utils, 'LOG', autospec=True)
    @mock.patch.object(molds, 'save_configuration', autospec=True)
    @mock.patch.object(redfish_utils, 'get_system', autospec=True)
    def test_export_configuration_success(self, mock_get_system,
                                          mock_save_configuration,
                                          mock_log):
        task = mock.Mock(node=self.node, context=self.context)
        fake_manager_oem1 = mock.Mock()
        fake_manager_oem1.export_system_configuration.side_effect = (
            sushy.exceptions.SushyError)
        fake_manager1 = mock.Mock()
        fake_manager1.get_oem_extension.return_value = fake_manager_oem1

        configuration = mock.Mock(status_code=200)
        configuration.json.return_value = (
            json.loads('{"prop1":"value1", "prop2":2}'))
        fake_manager_oem2 = mock.Mock()
        fake_manager_oem2.export_system_configuration.return_value = (
            configuration)
        fake_manager2 = mock.Mock()
        fake_manager2.get_oem_extension.return_value = fake_manager_oem2
        mock_get_system.return_value.managers = [fake_manager1, fake_manager2]
        self.management.export_configuration(task, 'edge')

        fake_manager_oem2.export_system_configuration.assert_called_once_with(
            include_destructive_fields=False)
        mock_save_configuration.assert_called_once_with(
            task,
            'edge',
            {"oem": {"interface": "idrac-redfish",
             "data": {"prop1": "value1", "prop2": 2}}})
        self.assertEqual(mock_log.debug.call_count, 1)
        self.assertEqual(mock_log.info.call_count, 1)

    def test_import_configuration_name_missing(self):
        task = mock.Mock(node=self.node, context=self.context)
        self.assertRaises(exception.MissingParameterValue,
                          self.management.import_configuration, task, None)

    @mock.patch.object(molds, 'get_configuration', autospec=True)
    def test_import_configuration_file_not_found(self, mock_get_configuration):
        task = mock.Mock(node=self.node, context=self.context)
        mock_get_configuration.return_value = None

        self.assertRaises(exception.DracOperationError,
                          self.management.import_configuration, task, 'edge')

    @mock.patch.object(molds, 'get_configuration', autospec=True)
    @mock.patch.object(redfish_utils, 'get_system', autospec=True)
    def test_import_configuration_incorrect_schema(self, mock_get_system,
                                                   mock_get_configuration):
        task = mock.Mock(node=self.node, context=self.context)
        fake_manager_oem1 = mock.Mock()
        fake_manager1 = mock.Mock()
        fake_manager1.get_oem_extension.return_value = fake_manager_oem1
        mock_get_system.return_value.managers = [fake_manager1]
        mock_get_configuration.return_value = json.loads(
            '{"oem": {"interface": "idrac-wsman", '
            '"data": {"prop1": "value1", "prop2": 2}}}')

        self.assertRaises(exception.InvalidParameterValue,
                          self.management.import_configuration, task, 'edge')

    @mock.patch.object(deploy_utils, 'set_async_step_flags', autospec=True)
    @mock.patch.object(deploy_utils, 'build_agent_options', autospec=True)
    @mock.patch.object(manager_utils, 'node_power_action', autospec=True)
    @mock.patch.object(drac_utils, 'LOG', autospec=True)
    @mock.patch.object(molds, 'get_configuration', autospec=True)
    @mock.patch.object(redfish_utils, 'get_system', autospec=True)
    def test_import_configuration_success(
            self, mock_get_system, mock_get_configuration, mock_log,
            mock_power, mock_build_agent_options,
            mock_set_async_step_flags):
        deploy_opts = mock.Mock()
        mock_build_agent_options.return_value = deploy_opts
        task = mock.Mock(node=self.node, context=self.context)
        fake_manager_oem1 = mock.Mock()
        fake_manager_oem1.import_system_configuration.side_effect = (
            sushy.exceptions.SushyError)
        fake_manager1 = mock.Mock()
        fake_manager1.get_oem_extension.return_value = fake_manager_oem1
        fake_manager_oem2 = mock.Mock()
        fake_manager2 = mock.Mock()
        fake_manager2.get_oem_extension.return_value = fake_manager_oem2
        mock_get_system.return_value.managers = [fake_manager1, fake_manager2]
        mock_get_configuration.return_value = json.loads(
            '{"oem": {"interface": "idrac-redfish", '
            '"data": {"prop1": "value1", "prop2": 2}}}')

        result = self.management.import_configuration(task, 'edge')
        self.assertEqual(states.DEPLOYWAIT, result)

        fake_manager_oem2.import_system_configuration.assert_called_once_with(
            '{"prop1": "value1", "prop2": 2}')
        self.assertEqual(mock_log.debug.call_count, 1)

        mock_set_async_step_flags.assert_called_once_with(
            task.node, reboot=True, skip_current_step=True, polling=True)
        mock_build_agent_options.assert_called_once_with(task.node)
        task.driver.boot.prepare_ramdisk.assert_called_once_with(
            task, deploy_opts)

    @mock.patch.object(drac_mgmt.DracRedfishManagement,
                       'import_configuration', autospec=True)
    def test_import_export_configuration_success(self, mock_import):
        task = mock.Mock(node=self.node, context=self.context)

        self.management.import_export_configuration(
            task, 'https://server/edge_import', 'https://server/edge_export')

        mock_import.assert_called_once_with(self.management, task,
                                            'https://server/edge_import')
        self.assertEqual(
            'https://server/edge_export',
            self.node.driver_internal_info.get(
                'export_configuration_location'))

    @mock.patch.object(task_manager, 'acquire', autospec=True)
    def test__query_import_configuration_not_drac(self, mock_acquire):
        driver_internal_info = {'import_task_monitor_url': '/TaskService/123'}
        self.node.driver_internal_info = driver_internal_info
        self.node.save()
        mock_manager = mock.Mock()
        node_list = [(self.node.uuid, 'not-idrac', '', driver_internal_info)]
        mock_manager.iter_nodes.return_value = node_list
        task = mock.Mock(node=self.node,
                         driver=mock.Mock(management=mock.Mock()))
        mock_acquire.return_value = mock.MagicMock(
            __enter__=mock.MagicMock(return_value=task))
        self.management._check_import_configuration_task = mock.Mock()

        self.management._query_import_configuration_status(mock_manager,
                                                           self.context)

        self.management._check_import_configuration_task.assert_not_called()

    @mock.patch.object(task_manager, 'acquire', autospec=True)
    def test__query_import_configuration_status_no_task_monitor_url(
            self, mock_acquire):
        driver_internal_info = {'something': 'else'}
        self.node.driver_internal_info = driver_internal_info
        self.node.save()
        mock_manager = mock.Mock()
        node_list = [(self.node.uuid, 'idrac', '', driver_internal_info)]
        mock_manager.iter_nodes.return_value = node_list
        task = mock.Mock(node=self.node,
                         driver=mock.Mock(management=self.management))
        mock_acquire.return_value = mock.MagicMock(
            __enter__=mock.MagicMock(return_value=task))
        self.management._check_import_configuration_task = mock.Mock()

        self.management._query_import_configuration_status(mock_manager,
                                                           self.context)

        self.management._check_import_configuration_task.assert_not_called()

    @mock.patch.object(periodics.LOG, 'info', autospec=True)
    @mock.patch.object(task_manager, 'acquire', autospec=True)
    def test__query_import_configuration_status_node_notfound(
            self, mock_acquire, mock_log):
        driver_internal_info = {'import_task_monitor_url': '/TaskService/123'}
        self.node.driver_internal_info = driver_internal_info
        self.node.save()
        mock_manager = mock.Mock()
        node_list = [(self.node.uuid, 'idrac', '', driver_internal_info)]
        mock_manager.iter_nodes.return_value = node_list
        mock_acquire.side_effect = exception.NodeNotFound
        task = mock.Mock(node=self.node,
                         driver=mock.Mock(management=self.management))
        mock_acquire.return_value = mock.MagicMock(
            __enter__=mock.MagicMock(return_value=task))
        self.management._check_import_configuration_task = mock.Mock()

        self.management._query_import_configuration_status(mock_manager,
                                                           self.context)

        self.management._check_import_configuration_task.assert_not_called()
        self.assertTrue(mock_log.called)

    @mock.patch.object(periodics.LOG, 'info', autospec=True)
    @mock.patch.object(task_manager, 'acquire', autospec=True)
    def test__query_import_configuration_status_node_locked(
            self, mock_acquire, mock_log):
        driver_internal_info = {'import_task_monitor_url': '/TaskService/123'}
        self.node.driver_internal_info = driver_internal_info
        self.node.save()
        mock_manager = mock.Mock()
        node_list = [(self.node.uuid, 'idrac', '', driver_internal_info)]
        mock_manager.iter_nodes.return_value = node_list
        mock_acquire.side_effect = exception.NodeLocked
        task = mock.Mock(node=self.node,
                         driver=mock.Mock(management=self.management))
        mock_acquire.return_value = mock.MagicMock(
            __enter__=mock.MagicMock(return_value=task))
        self.management._check_import_configuration_task = mock.Mock()

        self.management._query_import_configuration_status(mock_manager,
                                                           self.context)

        self.management._check_import_configuration_task.assert_not_called()
        self.assertTrue(mock_log.called)

    @mock.patch.object(task_manager, 'acquire', autospec=True)
    def test__query_import_configuration_status(self, mock_acquire):
        driver_internal_info = {'import_task_monitor_url': '/TaskService/123'}
        self.node.driver_internal_info = driver_internal_info
        self.node.save()
        mock_manager = mock.Mock()
        node_list = [(self.node.uuid, 'idrac', '', driver_internal_info)]
        mock_manager.iter_nodes.return_value = node_list
        task = mock.Mock(node=self.node,
                         driver=mock.Mock(management=self.management))
        mock_acquire.return_value = mock.MagicMock(
            __enter__=mock.MagicMock(return_value=task))
        self.management._check_import_configuration_task = mock.Mock()

        self.management._query_import_configuration_status(mock_manager,
                                                           self.context)

        (self.management
            ._check_import_configuration_task
            .assert_called_once_with(task, '/TaskService/123'))

    @mock.patch.object(redfish_utils, 'get_task_monitor', autospec=True)
    def test__check_import_configuration_task_missing(
            self, mock_get_task_monitor):
        mock_get_task_monitor.side_effect = exception.RedfishError(
            error='Task not found')
        self.management._set_success = mock.Mock()
        self.management._set_failed = mock.Mock()

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            self.management._check_import_configuration_task(
                task, '/TaskService/123')

            self.management._set_failed.assert_called_once_with(
                task, mock.ANY, mock.ANY)
            self.management._set_success.assert_not_called()
            self.assertIsNone(
                task.node.driver_internal_info.get('import_task_monitor_url'))

    @mock.patch.object(drac_mgmt.LOG, 'debug', autospec=True)
    @mock.patch.object(redfish_utils, 'get_task_monitor', autospec=True)
    def test__check_import_configuration_task_still_processing(
            self, mock_get_task_monitor, mock_log):
        driver_internal_info = {'import_task_monitor_url': '/TaskService/123'}
        self.node.driver_internal_info = driver_internal_info
        self.node.save()

        mock_task_monitor = mock.Mock()
        mock_task_monitor.is_processing = True
        mock_get_task_monitor.return_value = mock_task_monitor

        self.management._set_success = mock.Mock()
        self.management._set_failed = mock.Mock()

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            self.management._check_import_configuration_task(
                task, '/TaskService/123')

            self.management._set_success.assert_not_called()
            self.management._set_failed.assert_not_called()
            self.assertTrue(mock_log.called)
            self.assertEqual(
                '/TaskService/123',
                task.node.driver_internal_info.get('import_task_monitor_url'))

    @mock.patch.object(redfish_utils, 'get_task_monitor', autospec=True)
    def test__check_import_configuration_task_failed(
            self, mock_get_task_monitor):
        driver_internal_info = {'import_task_monitor_url': '/TaskService/123'}
        self.node.driver_internal_info = driver_internal_info
        self.node.save()

        mock_message = mock.Mock()
        mock_message.message = 'Firmware upgrade failed'
        mock_import_task = mock.Mock()
        mock_import_task.task_state = sushy.TASK_STATE_COMPLETED
        mock_import_task.task_status = 'Failed'
        mock_import_task.messages = [mock_message]
        mock_task_monitor = mock.Mock()
        mock_task_monitor.is_processing = False
        mock_task_monitor.get_task.return_value = mock_import_task
        mock_get_task_monitor.return_value = mock_task_monitor

        self.management._set_success = mock.Mock()
        self.management._set_failed = mock.Mock()

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            self.management._check_import_configuration_task(
                task, '/TaskService/123')

            self.management._set_failed.assert_called_once_with(
                task, mock.ANY,
                "Failed import configuration task: /TaskService/123. Message: "
                "'Firmware upgrade failed'.")
            self.management._set_success.assert_not_called()
            self.assertIsNone(
                task.node.driver_internal_info.get('import_task_monitor_url'))

    @mock.patch.object(redfish_utils, 'get_task_monitor', autospec=True)
    def test__check_import_configuration_task_partial_failed(
            self, mock_get_task_monitor):
        driver_internal_info = {'import_task_monitor_url': '/TaskService/123'}
        self.node.driver_internal_info = driver_internal_info
        self.node.save()

        mock_message1 = mock.Mock()
        mock_message1.message_id = 'SYS413'
        mock_message1.message = 'The operation successfully completed'
        mock_message1.severity = sushy.SEVERITY_OK
        mock_message2 = mock.Mock()
        mock_message2.message_id = 'SYS055'
        mock_message2.message = 'Firmware upgrade failed'
        mock_message2.severity = sushy.SEVERITY_CRITICAL
        mock_import_task = mock.Mock()
        mock_import_task.task_state = sushy.TASK_STATE_COMPLETED
        mock_import_task.task_status = sushy.HEALTH_OK
        mock_import_task.messages = [mock_message1, mock_message2]
        mock_task_monitor = mock.Mock()
        mock_task_monitor.is_processing = False
        mock_task_monitor.get_task.return_value = mock_import_task
        mock_get_task_monitor.return_value = mock_task_monitor

        self.management._set_success = mock.Mock()
        self.management._set_failed = mock.Mock()

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            self.management._check_import_configuration_task(
                task, '/TaskService/123')

            self.management._set_failed.assert_called_once_with(
                task, mock.ANY,
                "Failed import configuration task: /TaskService/123. Message: "
                "'Firmware upgrade failed'.")
            self.management._set_success.assert_not_called()
            self.assertIsNone(
                task.node.driver_internal_info.get('import_task_monitor_url'))

    @mock.patch.object(redfish_utils, 'get_task_monitor', autospec=True)
    def test__check_import_configuration_task_partial_failed_idrac5(
            self, mock_get_task_monitor):
        driver_internal_info = {'import_task_monitor_url': '/TaskService/123'}
        self.node.driver_internal_info = driver_internal_info
        self.node.save()

        mock_message1 = mock.Mock()
        mock_message1.message = ('Import of Server Configuration Profile '
                                 'operation completed with errors')
        mock_message1.message_id = 'IDRAC.2.4.SYS055'
        mock_import_task = mock.Mock()
        mock_import_task.task_state = sushy.TASK_STATE_COMPLETED
        mock_import_task.task_status = sushy.HEALTH_OK
        mock_import_task.messages = [mock_message1]
        mock_task_monitor = mock.Mock()
        mock_task_monitor.is_processing = False
        mock_task_monitor.get_task.return_value = mock_import_task
        mock_get_task_monitor.return_value = mock_task_monitor

        self.management._set_success = mock.Mock()
        self.management._set_failed = mock.Mock()

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            self.management._check_import_configuration_task(
                task, '/TaskService/123')

            self.management._set_failed.assert_called_once_with(
                task, mock.ANY,
                "Failed import configuration task: /TaskService/123. Message: "
                "'Import of Server Configuration Profile "
                "operation completed with errors'.")
            self.management._set_success.assert_not_called()
            self.assertIsNone(
                task.node.driver_internal_info.get('import_task_monitor_url'))

    @mock.patch.object(redfish_utils, 'get_task_monitor', autospec=True)
    def test__check_import_configuration_task(self, mock_get_task_monitor):
        driver_internal_info = {'import_task_monitor_url': '/TaskService/123'}
        self.node.driver_internal_info = driver_internal_info
        self.node.save()

        mock_message = mock.Mock()
        mock_message.message_id = 'SYS413'
        mock_message.message = 'Configuration import done'
        mock_message.severity = sushy.SEVERITY_OK
        mock_import_task = mock.Mock()
        mock_import_task.task_state = sushy.TASK_STATE_COMPLETED
        mock_import_task.task_status = sushy.HEALTH_OK
        mock_import_task.messages = [mock_message]
        mock_task_monitor = mock.Mock()
        mock_task_monitor.is_processing = False
        mock_task_monitor.get_task.return_value = mock_import_task
        mock_get_task_monitor.return_value = mock_task_monitor

        self.management._set_success = mock.Mock()
        self.management._set_failed = mock.Mock()

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            self.management._check_import_configuration_task(
                task, '/TaskService/123')

            self.management._set_success.assert_called_once_with(task)
            self.management._set_failed.assert_not_called()
            self.assertIsNone(
                task.node.driver_internal_info.get('import_task_monitor_url'))

    @mock.patch.object(redfish_utils, 'get_task_monitor', autospec=True)
    def test__check_import_configuration_task_with_export_failed(
            self, mock_get_task_monitor):
        driver_internal_info = {
            'import_task_monitor_url': '/TaskService/123',
            'export_configuration_location': 'https://server/export1'}
        self.node.driver_internal_info = driver_internal_info
        self.node.save()

        mock_message = mock.Mock()
        mock_message.message_id = 'SYS413'
        mock_message.message = 'Configuration import done'
        mock_message.severity = sushy.SEVERITY_OK
        mock_import_task = mock.Mock()
        mock_import_task.task_state = sushy.TASK_STATE_COMPLETED
        mock_import_task.task_status = sushy.HEALTH_OK
        mock_import_task.messages = [mock_message]
        mock_task_monitor = mock.Mock()
        mock_task_monitor.is_processing = False
        mock_task_monitor.get_task.return_value = mock_import_task
        mock_get_task_monitor.return_value = mock_task_monitor

        self.management._set_success = mock.Mock()
        self.management._set_failed = mock.Mock()
        mock_export = mock.Mock()
        mock_export.side_effect = exception.IronicException
        self.management.export_configuration = mock_export

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            self.management._check_import_configuration_task(
                task, '/TaskService/123')

            self.management.export_configuration.assert_called_once_with(
                task, 'https://server/export1')
            self.management._set_success.assert_not_called()
            self.assertIsNone(
                task.node.driver_internal_info.get('import_task_monitor_url'))
            self.assertIsNone(
                task.node.driver_internal_info.get(
                    'export_configuration_location'))
            self.management._set_failed.assert_called_with(
                task, mock.ANY,
                'Failed export configuration. An unknown exception occurred.')

    @mock.patch.object(redfish_utils, 'get_task_monitor', autospec=True)
    def test__check_import_configuration_task_with_export(
            self, mock_get_task_monitor):
        driver_internal_info = {
            'import_task_monitor_url': '/TaskService/123',
            'export_configuration_location': 'https://server/export1'}
        self.node.driver_internal_info = driver_internal_info
        self.node.save()

        mock_message = mock.Mock()
        mock_message.message_id = 'SYS413'
        mock_message.message = 'Configuration import done'
        mock_message.severity = sushy.SEVERITY_OK
        mock_import_task = mock.Mock()
        mock_import_task.task_state = sushy.TASK_STATE_COMPLETED
        mock_import_task.task_status = sushy.HEALTH_OK
        mock_import_task.messages = [mock_message]
        mock_task_monitor = mock.Mock()
        mock_task_monitor.is_processing = False
        mock_task_monitor.get_task.return_value = mock_import_task
        mock_get_task_monitor.return_value = mock_task_monitor

        self.management._set_success = mock.Mock()
        self.management._set_failed = mock.Mock()
        self.management.export_configuration = mock.Mock()

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            self.management._check_import_configuration_task(
                task, '/TaskService/123')

            self.management.export_configuration.assert_called_once_with(
                task, 'https://server/export1')
            self.management._set_success.assert_called_once_with(task)
            self.assertIsNone(
                task.node.driver_internal_info.get('import_task_monitor_url'))
            self.assertIsNone(
                task.node.driver_internal_info.get(
                    'export_configuration_location'))
            self.management._set_failed.assert_not_called()

    @mock.patch.object(manager_utils, 'notify_conductor_resume_deploy',
                       autospec=True)
    @mock.patch.object(manager_utils, 'notify_conductor_resume_clean',
                       autospec=True)
    def test__set_success_clean(self, mock_notify_clean, mock_notify_deploy):
        self.node.clean_step = {'test': 'value'}
        self.node.save()
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            self.management._set_success(task)

            mock_notify_clean.assert_called_once_with(task)

    @mock.patch.object(manager_utils, 'notify_conductor_resume_deploy',
                       autospec=True)
    @mock.patch.object(manager_utils, 'notify_conductor_resume_clean',
                       autospec=True)
    def test__set_success_deploy(self, mock_notify_clean, mock_notify_deploy):
        self.node.clean_step = None
        self.node.save()
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            self.management._set_success(task)

            mock_notify_deploy.assert_called_once_with(task)

    @mock.patch.object(manager_utils, 'deploying_error_handler',
                       autospec=True)
    @mock.patch.object(manager_utils, 'cleaning_error_handler',
                       autospec=True)
    def test__set_failed_clean(self, mock_clean_handler, mock_deploy_handler):
        self.node.clean_step = {'test': 'value'}
        self.node.save()

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            self.management._set_failed(task, 'error', 'log message')

            mock_clean_handler.assert_called_once_with(
                task, 'error', 'log message')

    @mock.patch.object(manager_utils, 'deploying_error_handler',
                       autospec=True)
    @mock.patch.object(manager_utils, 'cleaning_error_handler',
                       autospec=True)
    def test__set_failed_deploy(self, mock_clean_handler, mock_deploy_handler):
        self.node.clean_step = None
        self.node.save()

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            self.management._set_failed(task, 'error', 'log message')

            mock_deploy_handler.assert_called_once_with(
                task, 'error', 'log message')

    @mock.patch.object(drac_utils, 'redfish_utils', autospec=True)
    def test_clear_job_queue(self, mock_redfish_utils):
        mock_system = mock_redfish_utils.get_system.return_value
        mock_manager = mock.MagicMock()
        mock_system.managers = [mock_manager]
        mock_manager_oem = mock_manager.get_oem_extension.return_value

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.driver.management.clear_job_queue(task)
            mock_manager_oem.job_service.delete_jobs.assert_called_once_with(
                job_ids=['JID_CLEARALL'])

    @mock.patch.object(drac_mgmt, 'LOG', autospec=True)
    @mock.patch.object(drac_utils, 'redfish_utils', autospec=True)
    def test_clear_job_queue_missing_attr_verify_step(self,
                                                      mock_redfish_utils,
                                                      mock_log):
        mock_system = mock_redfish_utils.get_system.return_value
        mock_manager = mock.MagicMock()
        mock_system.managers = [mock_manager]
        mock_manager_oem = mock_manager.get_oem_extension.return_value
        mock_manager_oem.job_service.delete_jobs.side_effect = (
            exception.RedfishError("Oem/Dell/DellJobService is missing"))
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.node.provision_state = states.VERIFYING
            task.driver.management.clear_job_queue(task)
            mock_log.warning.assert_called_once_with(
                'iDRAC on node %(node)s does not support '
                'clearing Lifecycle Controller job queue '
                'using the idrac-redfish driver. '
                'If using iDRAC9, consider upgrading firmware.',
                {'node': task.node.uuid})

    @mock.patch.object(drac_mgmt, 'LOG', autospec=True)
    @mock.patch.object(drac_utils, 'redfish_utils', autospec=True)
    def test_clear_job_queue_missing_attr_clean_step(self,
                                                     mock_redfish_utils,
                                                     mock_log):
        mock_system = mock_redfish_utils.get_system.return_value
        mock_manager = mock.MagicMock()
        mock_system.managers = [mock_manager]
        mock_manager_oem = mock_manager.get_oem_extension.return_value
        mock_manager_oem.job_service.delete_jobs.side_effect = (
            exception.RedfishError("Oem/Dell/DellJobService is missing"))
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.node.provision_state = states.CLEANING
            self.assertRaises(ironic.common.exception.RedfishError,
                              task.driver.management.clear_job_queue, task)

    @mock.patch.object(redfish_utils, 'wait_until_get_system_ready',
                       autospec=True)
    @mock.patch.object(drac_utils, 'redfish_utils', autospec=True)
    def test_reset_idrac(self, mock_redfish_utils, mock_wait_system_ready):
        mock_system = mock_redfish_utils.get_system.return_value
        mock_manager = mock.MagicMock()
        mock_system.managers = [mock_manager]
        mock_manager_oem = mock_manager.get_oem_extension.return_value

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.driver.management.reset_idrac(task)
            mock_manager_oem.reset_idrac.assert_called_once_with()

    @mock.patch.object(redfish_utils, 'wait_until_get_system_ready',
                       autospec=True)
    @mock.patch.object(drac_mgmt, 'LOG', autospec=True)
    @mock.patch.object(drac_utils, 'redfish_utils', autospec=True)
    def test_reset_idrac_missing_attr_verify_step(self,
                                                  mock_redfish_utils,
                                                  mock_log,
                                                  mock_wait_system_ready):
        mock_system = mock_redfish_utils.get_system.return_value
        mock_manager = mock.MagicMock()
        mock_system.managers = [mock_manager]
        mock_manager_oem = mock_manager.get_oem_extension.return_value
        mock_manager_oem.reset_idrac.side_effect = (
            exception.RedfishError("Oem/Dell/DelliDRACCardService is missing"))
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.node.provision_state = states.VERIFYING
            task.driver.management.reset_idrac(task)
            mock_log.warning.assert_called_once_with(
                'iDRAC on node %(node)s does not support '
                'iDRAC reset using the idrac-redfish driver. '
                'If using iDRAC9, consider upgrading firmware. ',
                {'node': task.node.uuid})

    @mock.patch.object(redfish_utils, 'wait_until_get_system_ready',
                       autospec=True)
    @mock.patch.object(drac_mgmt, 'LOG', autospec=True)
    @mock.patch.object(drac_utils, 'redfish_utils', autospec=True)
    def test_reset_idrac_missing_attr_clean_step(self,
                                                 mock_redfish_utils,
                                                 mock_log,
                                                 mock_wait_system_ready):
        mock_system = mock_redfish_utils.get_system.return_value
        mock_manager = mock.MagicMock()
        mock_system.managers = [mock_manager]
        mock_manager_oem = mock_manager.get_oem_extension.return_value
        mock_manager_oem.reset_idrac.side_effect = (
            exception.RedfishError("Oem/Dell/DelliDRACCardService is missing"))
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.node.provision_state = states.CLEANING
            self.assertRaises(ironic.common.exception.RedfishError,
                              task.driver.management.reset_idrac, task)

    @mock.patch.object(redfish_utils, 'wait_until_get_system_ready',
                       autospec=True)
    @mock.patch.object(drac_utils, 'redfish_utils', autospec=True)
    def test_known_good_state(self, mock_redfish_utils,
                              mock_wait_system_ready):
        mock_system = mock_redfish_utils.get_system.return_value
        mock_manager = mock.MagicMock()
        mock_system.managers = [mock_manager]
        mock_manager_oem = mock_manager.get_oem_extension.return_value

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.driver.management.known_good_state(task)
            mock_manager_oem.job_service.delete_jobs.assert_called_once_with(
                job_ids=['JID_CLEARALL'])
            mock_manager_oem.reset_idrac.assert_called_once_with()

    def test__validate_conf_mold(self):
        drac_mgmt._validate_conf_mold({'oem': {'interface': 'idrac-redfish',
                                       'data': {'SystemConfiguration': {}}}})

    def test__validate_conf_mold_oem_missing(self):
        self.assertRaisesRegex(
            exception.InvalidParameterValue,
            "'oem' is a required property",
            drac_mgmt._validate_conf_mold,
            {'bios': {'reset': False}})

    def test__validate_conf_mold_interface_missing(self):
        self.assertRaisesRegex(
            exception.InvalidParameterValue,
            "'interface' is a required property",
            drac_mgmt._validate_conf_mold,
            {'oem': {'data': {'SystemConfiguration': {}}}})

    def test__validate_conf_mold_interface_not_supported(self):
        self.assertRaisesRegex(
            exception.InvalidParameterValue,
            "'idrac-redfish' was expected",
            drac_mgmt._validate_conf_mold,
            {'oem': {'interface': 'idrac-wsman',
             'data': {'SystemConfiguration': {}}}})

    def test__validate_conf_mold_data_missing(self):
        self.assertRaisesRegex(
            exception.InvalidParameterValue,
            "'data' is a required property",
            drac_mgmt._validate_conf_mold,
            {'oem': {'interface': 'idrac-redfish'}})

    def test__validate_conf_mold_data_empty(self):
        try:
            self.assertRaisesRegex(
                exception.InvalidParameterValue,
                "does not have enough properties",
                drac_mgmt._validate_conf_mold,
                {'oem': {'interface': 'idrac-redfish', 'data': {}}})
        except Exception:
            self.assertRaisesRegex(
                exception.InvalidParameterValue,
                "should be non-empty",
                drac_mgmt._validate_conf_mold,
                {'oem': {'interface': 'idrac-redfish', 'data': {}}})
