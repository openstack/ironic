# Copyright 2018 FUJITSU LIMITED
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
Test class for iRMC periodic tasks
"""

from unittest import mock

from oslo_utils import uuidutils

from ironic.conductor import task_manager
from ironic.drivers.modules.irmc import common as irmc_common
from ironic.drivers.modules.irmc import raid as irmc_raid
from ironic.drivers.modules import noop
from ironic.tests.unit.drivers.modules.irmc import test_common
from ironic.tests.unit.objects import utils as obj_utils


class iRMCPeriodicTaskTestCase(test_common.BaseIRMCTest):

    def setUp(self):
        super(iRMCPeriodicTaskTestCase, self).setUp()
        self.node_2 = obj_utils.create_test_node(
            self.context, driver='fake-hardware',
            uuid=uuidutils.generate_uuid())
        self.driver = mock.Mock(raid=irmc_raid.IRMCRAID())
        self.raid_config = {
            'logical_disks': [
                {'controller': 'RAIDAdapter0'},
                {'irmc_raid_info':
                    {' size': {'#text': 465, '@Unit': 'GB'},
                     'logical_drive_number': 0,
                     'name': 'LogicalDrive_0',
                     'raid_level': '1'}}]}
        self.target_raid_config = {
            'logical_disks': [
                {
                    'key': 'value'
                }]}

    @mock.patch.object(irmc_common, 'get_irmc_report')
    def test__query_raid_config_fgi_status_without_node(
            self, report_mock):
        mock_manager = mock.Mock()
        node_list = []
        mock_manager.iter_nodes.return_value = node_list
        raid_object = irmc_raid.IRMCRAID()
        raid_object._query_raid_config_fgi_status(mock_manager, None)
        self.assertEqual(0, report_mock.call_count)

    @mock.patch.object(irmc_common, 'get_irmc_report')
    @mock.patch.object(task_manager, 'acquire', autospec=True)
    def test__query_raid_config_fgi_status_without_raid_object(
            self, mock_acquire, report_mock):
        mock_manager = mock.Mock()
        raid_config = self.raid_config
        task = mock.Mock(node=self.node, driver=self.driver)
        mock_acquire.return_value = mock.MagicMock(
            __enter__=mock.MagicMock(return_value=task))
        node_list = [(self.node.uuid, 'irmc', '', raid_config)]
        mock_manager.iter_nodes.return_value = node_list
        task.driver.raid = noop.NoRAID()
        raid_object = irmc_raid.IRMCRAID()
        raid_object._query_raid_config_fgi_status(mock_manager,
                                                  self.context)
        self.assertEqual(0, report_mock.call_count)

    @mock.patch.object(irmc_common, 'get_irmc_report')
    @mock.patch.object(task_manager, 'acquire', autospec=True)
    def test__query_raid_config_fgi_status_without_input(
            self, mock_acquire, report_mock):
        mock_manager = mock.Mock()
        raid_config = self.raid_config
        task = mock.Mock(node=self.node, driver=self.driver)
        mock_acquire.return_value = mock.MagicMock(
            __enter__=mock.MagicMock(return_value=task))
        node_list = [(self.node.uuid, 'irmc', '', raid_config)]
        mock_manager.iter_nodes.return_value = node_list
        # Set none target_raid_config input
        task.node.target_raid_config = None
        task.node.save()
        task.driver.raid._query_raid_config_fgi_status(mock_manager,
                                                       self.context)
        self.assertEqual(0, report_mock.call_count)

    @mock.patch.object(irmc_common, 'get_irmc_report')
    @mock.patch.object(task_manager, 'acquire', autospec=True)
    def test__query_raid_config_fgi_status_without_raid_config(
            self, mock_acquire, report_mock):
        mock_manager = mock.Mock()
        raid_config = {}
        task = mock.Mock(node=self.node, driver=self.driver)
        mock_acquire.return_value = mock.MagicMock(
            __enter__=mock.MagicMock(return_value=task))
        node_list = [(self.node.uuid, 'irmc', '', raid_config)]
        mock_manager.iter_nodes.return_value = node_list
        task.driver.raid._query_raid_config_fgi_status(mock_manager,
                                                       self.context)
        self.assertEqual(0, report_mock.call_count)

    @mock.patch.object(irmc_common, 'get_irmc_report')
    @mock.patch.object(task_manager, 'acquire', autospec=True)
    def test__query_raid_config_fgi_status_without_fgi_status(
            self, mock_acquire, report_mock):
        mock_manager = mock.Mock()
        raid_config = {
            'logical_disks': [
                {'controller': 'RAIDAdapter0'},
                {'irmc_raid_info':
                    {' size': {'#text': 465, '@Unit': 'GB'},
                     'logical_drive_number': 0,
                     'name': 'LogicalDrive_0',
                     'raid_level': '1'}}]}
        task = mock.Mock(node=self.node, driver=self.driver)
        mock_acquire.return_value = mock.MagicMock(
            __enter__=mock.MagicMock(return_value=task))
        node_list = [(self.node.uuid, 'irmc', '', raid_config)]
        mock_manager.iter_nodes.return_value = node_list
        task.driver.raid._query_raid_config_fgi_status(mock_manager,
                                                       self.context)
        self.assertEqual(0, report_mock.call_count)

    @mock.patch.object(irmc_common, 'get_irmc_report')
    @mock.patch.object(task_manager, 'acquire', autospec=True)
    def test__query_raid_config_fgi_status_other_clean_state(
            self, mock_acquire, report_mock):
        mock_manager = mock.Mock()
        raid_config = self.raid_config
        task = mock.Mock(node=self.node, driver=self.driver)
        mock_acquire.return_value = mock.MagicMock(
            __enter__=mock.MagicMock(return_value=task))
        node_list = [(self.node.uuid, 'irmc', '', raid_config)]
        mock_manager.iter_nodes.return_value = node_list
        # Set provision state value
        task.node.provision_state = 'cleaning'
        task.node.save()
        task.driver.raid._query_raid_config_fgi_status(mock_manager,
                                                       self.context)
        self.assertEqual(0, report_mock.call_count)

    @mock.patch('ironic.drivers.modules.irmc.raid.IRMCRAID._set_clean_failed')
    @mock.patch('ironic.drivers.modules.irmc.raid._get_fgi_status')
    @mock.patch.object(irmc_common, 'get_irmc_report')
    @mock.patch.object(task_manager, 'acquire', autospec=True)
    def test__query_raid_config_fgi_status_completing_status(
            self, mock_acquire, report_mock, fgi_mock, clean_fail_mock):
        mock_manager = mock.Mock()
        fgi_mock.return_value = 'completing'
        node_list = [(self.node.uuid, 'irmc', '', self.raid_config)]
        mock_manager.iter_nodes.return_value = node_list
        task = mock.Mock(node=self.node, driver=self.driver)
        mock_acquire.return_value = mock.MagicMock(
            __enter__=mock.MagicMock(return_value=task))
        # Set provision state value
        task.node.provision_state = 'clean wait'
        task.node.target_raid_config = self.target_raid_config
        task.node.raid_config = self.raid_config
        task.node.save()

        task.driver.raid._query_raid_config_fgi_status(mock_manager,
                                                       self.context)
        self.assertEqual(0, clean_fail_mock.call_count)
        report_mock.assert_called_once_with(task.node)
        fgi_mock.assert_called_once_with(report_mock.return_value,
                                         self.node.uuid)

    @mock.patch('ironic.drivers.modules.irmc.raid.IRMCRAID._set_clean_failed')
    @mock.patch('ironic.drivers.modules.irmc.raid._get_fgi_status')
    @mock.patch.object(irmc_common, 'get_irmc_report')
    @mock.patch.object(task_manager, 'acquire', autospec=True)
    def test__query_raid_config_fgi_status_with_clean_fail(
            self, mock_acquire, report_mock, fgi_mock, clean_fail_mock):
        mock_manager = mock.Mock()
        raid_config = self.raid_config
        fgi_mock.return_value = None
        fgi_status_dict = None
        task = mock.Mock(node=self.node, driver=self.driver)
        mock_acquire.return_value = mock.MagicMock(
            __enter__=mock.MagicMock(return_value=task))
        node_list = [(self.node.uuid, 'irmc', '', raid_config)]
        mock_manager.iter_nodes.return_value = node_list
        # Set provision state value
        task.node.provision_state = 'clean wait'
        task.node.target_raid_config = self.target_raid_config
        task.node.raid_config = self.raid_config
        task.node.save()
        task.driver.raid._query_raid_config_fgi_status(mock_manager,
                                                       self.context)
        clean_fail_mock.assert_called_once_with(task, fgi_status_dict)
        report_mock.assert_called_once_with(task.node)
        fgi_mock.assert_called_once_with(report_mock.return_value,
                                         self.node.uuid)

    @mock.patch('ironic.drivers.modules.irmc.raid.IRMCRAID._resume_cleaning')
    @mock.patch('ironic.drivers.modules.irmc.raid.IRMCRAID._set_clean_failed')
    @mock.patch('ironic.drivers.modules.irmc.raid._get_fgi_status')
    @mock.patch.object(irmc_common, 'get_irmc_report')
    @mock.patch.object(task_manager, 'acquire', autospec=True)
    def test__query_raid_config_fgi_status_with_complete_cleaning(
            self, mock_acquire, report_mock, fgi_mock, clean_fail_mock,
            clean_mock):
        mock_manager = mock.Mock()
        raid_config = self.raid_config
        fgi_mock.return_value = {'0': 'Idle', '1': 'Idle'}
        task = mock.Mock(node=self.node, driver=self.driver)
        mock_acquire.return_value = mock.MagicMock(
            __enter__=mock.MagicMock(return_value=task))
        node_list = [(self.node.uuid, 'irmc', '', raid_config)]
        mock_manager.iter_nodes.return_value = node_list
        # Set provision state value
        task.node.provision_state = 'clean wait'
        task.node.target_raid_config = self.target_raid_config
        task.node.save()
        task.driver.raid._query_raid_config_fgi_status(mock_manager,
                                                       self.context)
        self.assertEqual(0, clean_fail_mock.call_count)
        report_mock.assert_called_once_with(task.node)
        fgi_mock.assert_called_once_with(report_mock.return_value,
                                         self.node.uuid)
        clean_mock.assert_called_once_with(task)

    @mock.patch('ironic.drivers.modules.irmc.raid.IRMCRAID._resume_cleaning')
    @mock.patch('ironic.drivers.modules.irmc.raid.IRMCRAID._set_clean_failed')
    @mock.patch('ironic.drivers.modules.irmc.raid._get_fgi_status')
    @mock.patch.object(irmc_common, 'get_irmc_report')
    @mock.patch.object(task_manager, 'acquire', autospec=True)
    def test__query_raid_config_fgi_status_with_two_nodes_without_raid_config(
            self, mock_acquire, report_mock, fgi_mock, clean_fail_mock,
            clean_mock):
        mock_manager = mock.Mock()
        raid_config = self.raid_config
        raid_config_2 = {}
        fgi_mock.return_value = {'0': 'Idle', '1': 'Idle'}
        task = mock.Mock(node=self.node, driver=self.driver)
        mock_acquire.return_value = mock.MagicMock(
            __enter__=mock.MagicMock(return_value=task))
        node_list = [(self.node_2.uuid, 'irmc', '', raid_config_2),
                     (self.node.uuid, 'irmc', '', raid_config)]
        mock_manager.iter_nodes.return_value = node_list
        # Set provision state value
        task.node.provision_state = 'clean wait'
        task.node.target_raid_config = self.target_raid_config
        task.node.save()
        task.driver.raid._query_raid_config_fgi_status(mock_manager,
                                                       self.context)
        self.assertEqual(0, clean_fail_mock.call_count)
        report_mock.assert_called_once_with(task.node)
        fgi_mock.assert_called_once_with(report_mock.return_value,
                                         self.node.uuid)
        clean_mock.assert_called_once_with(task)

    @mock.patch('ironic.drivers.modules.irmc.raid.IRMCRAID._resume_cleaning')
    @mock.patch('ironic.drivers.modules.irmc.raid.IRMCRAID._set_clean_failed')
    @mock.patch('ironic.drivers.modules.irmc.raid._get_fgi_status')
    @mock.patch.object(irmc_common, 'get_irmc_report')
    @mock.patch.object(task_manager, 'acquire', autospec=True)
    def test__query_raid_config_fgi_status_with_two_nodes_with_fgi_status_none(
            self, mock_acquire, report_mock, fgi_mock, clean_fail_mock,
            clean_mock):
        mock_manager = mock.Mock()
        raid_config = self.raid_config
        raid_config_2 = self.raid_config.copy()
        fgi_status_dict = {}
        fgi_mock.side_effect = [{}, {'0': 'Idle', '1': 'Idle'}]
        node_list = [(self.node_2.uuid, 'fake-hardware', '', raid_config_2),
                     (self.node.uuid, 'irmc', '', raid_config)]
        mock_manager.iter_nodes.return_value = node_list
        task = mock.Mock(node=self.node_2, driver=self.driver)
        mock_acquire.return_value = mock.MagicMock(
            __enter__=mock.MagicMock(return_value=task))
        task.node.provision_state = 'clean wait'
        task.node.target_raid_config = self.target_raid_config
        task.node.save()
        task.driver.raid._query_raid_config_fgi_status(mock_manager,
                                                       self.context)
        report_mock.assert_has_calls(
            [mock.call(task.node), mock.call(task.node)])
        fgi_mock.assert_has_calls([mock.call(report_mock.return_value,
                                             self.node_2.uuid),
                                   mock.call(report_mock.return_value,
                                             self.node_2.uuid)])
        clean_fail_mock.assert_called_once_with(task, fgi_status_dict)
        clean_mock.assert_called_once_with(task)
