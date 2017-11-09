# Copyright 2016 Hewlett Packard Enterprise Development LP.
# Copyright 2016 Universidade Federal de Campina Grande
# All Rights Reserved.
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

import mock

from ironic.conductor import task_manager
from ironic.drivers.modules.oneview import common as oneview_common
from ironic.drivers.modules.oneview import deploy_utils
from ironic.tests.unit.conductor import mgr_utils
from ironic.tests.unit.db import base as db_base
from ironic.tests.unit.db import utils as db_utils
from ironic.tests.unit.objects import utils as obj_utils


@mock.patch.object(
    oneview_common, 'get_oneview_client', spec_set=True, autospec=True)
class AgentPXEOneViewInspectTestCase(db_base.DbTestCase):

    def setUp(self):
        super(AgentPXEOneViewInspectTestCase, self).setUp()
        self.config(enabled=True, group='inspector')
        mgr_utils.mock_the_extension_manager(driver="agent_pxe_oneview")
        self.node = obj_utils.create_test_node(
            self.context, driver='agent_pxe_oneview',
            properties=db_utils.get_test_oneview_properties(),
            driver_info=db_utils.get_test_oneview_driver_info(),
        )

    def test_get_properties(self, mock_get_ov_client):
        expected = deploy_utils.get_properties()
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            self.assertEqual(expected, task.driver.inspect.get_properties())

    @mock.patch.object(oneview_common, 'verify_node_info', spec_set=True,
                       autospec=True)
    def test_validate(self, mock_verify_node_info, mock_get_ov_client):
        self.config(enabled=False, group='inspector')
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.driver.inspect.validate(task)
            mock_verify_node_info.assert_called_once_with(task.node)

    @mock.patch.object(deploy_utils, 'allocate_server_hardware_to_ironic')
    def test_inspect_hardware(self, mock_allocate_server_hardware_to_ironic,
                              mock_get_ov_client):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.driver.inspect.inspect_hardware(task)
            self.assertTrue(mock_allocate_server_hardware_to_ironic.called)


@mock.patch.object(
    oneview_common, 'get_oneview_client', spec_set=True, autospec=True)
class ISCSIPXEOneViewInspectTestCase(db_base.DbTestCase):

    def setUp(self):
        super(ISCSIPXEOneViewInspectTestCase, self).setUp()
        self.config(enabled=True, group='inspector')
        mgr_utils.mock_the_extension_manager(driver="iscsi_pxe_oneview")
        self.node = obj_utils.create_test_node(
            self.context, driver='iscsi_pxe_oneview',
            properties=db_utils.get_test_oneview_properties(),
            driver_info=db_utils.get_test_oneview_driver_info(),
        )

    def test_get_properties(self, mock_get_ov_client):
        expected = deploy_utils.get_properties()
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            self.assertEqual(expected, task.driver.inspect.get_properties())

    @mock.patch.object(oneview_common, 'verify_node_info', spec_set=True,
                       autospec=True)
    def test_validate(self, mock_verify_node_info, mock_get_ov_client):
        self.config(enabled=False, group='inspector')
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.driver.inspect.validate(task)
            mock_verify_node_info.assert_called_once_with(task.node)

    @mock.patch.object(deploy_utils, 'allocate_server_hardware_to_ironic')
    def test_inspect_hardware(self, mock_allocate_server_hardware_to_ironic,
                              mock_get_ov_client):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.driver.inspect.inspect_hardware(task)
            self.assertTrue(mock_allocate_server_hardware_to_ironic.called)
