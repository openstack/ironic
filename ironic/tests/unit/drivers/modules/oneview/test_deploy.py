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

from oslo_utils import importutils

from ironic.common import driver_factory
from ironic.drivers.modules.oneview import common
from ironic.drivers.modules.oneview import deploy
from ironic.drivers.modules.oneview import deploy_utils
from ironic import objects
from ironic.tests.unit.conductor import mgr_utils
from ironic.tests.unit.db import base as db_base
from ironic.tests.unit.db import utils as db_utils
from ironic.tests.unit.objects import utils as obj_utils

oneview_models = importutils.try_import('oneview_client.models')


@mock.patch.object(common, 'get_oneview_client', spec_set=True, autospec=True)
class OneViewPeriodicTasks(db_base.DbTestCase):

    def setUp(self):
        super(OneViewPeriodicTasks, self).setUp()
        self.config(manager_url='https://1.2.3.4', group='oneview')
        self.config(username='user', group='oneview')
        self.config(password='password', group='oneview')

        mgr_utils.mock_the_extension_manager(driver='fake_oneview')
        self.driver = driver_factory.get_driver('fake_oneview')

        self.node = obj_utils.create_test_node(
            self.context, driver='fake_oneview',
            properties=db_utils.get_test_oneview_properties(),
            driver_info=db_utils.get_test_oneview_driver_info(),
        )
        self.info = common.get_oneview_info(self.node)

    @mock.patch.object(objects.Node, 'get')
    @mock.patch.object(deploy_utils, 'is_node_in_use_by_oneview')
    def test__periodic_check_nodes_taken_by_oneview(
        self, mock_is_node_in_use_by_oneview, mock_get_node,
            mock_get_ov_client
    ):

        manager = mock.MagicMock(
            spec=['iter_nodes', 'update_node', 'do_provisioning_action']
        )

        manager.iter_nodes.return_value = [
            (self.node.uuid, 'fake_oneview')
        ]

        mock_get_node.return_value = self.node
        mock_is_node_in_use_by_oneview.return_value = True

        class OneViewDriverDeploy(deploy.OneViewPeriodicTasks):
            oneview_driver = 'fake_oneview'

        oneview_driver_deploy = OneViewDriverDeploy()
        oneview_driver_deploy._periodic_check_nodes_taken_by_oneview(
            manager, self.context
        )
        self.assertTrue(manager.update_node.called)
        self.assertTrue(manager.do_provisioning_action.called)
        self.assertTrue(self.node.maintenance)
        self.assertEqual(common.NODE_IN_USE_BY_ONEVIEW,
                         self.node.maintenance_reason)

    @mock.patch.object(deploy_utils, 'is_node_in_use_by_oneview')
    def test__periodic_check_nodes_freed_by_oneview(
        self, mock_is_node_in_use_by_oneview, mock_get_ov_client
    ):

        manager = mock.MagicMock(
            spec=['iter_nodes', 'update_node', 'do_provisioning_action']
        )

        manager.iter_nodes.return_value = [
            (self.node.uuid, 'fake_oneview',
             common.NODE_IN_USE_BY_ONEVIEW)
        ]

        mock_is_node_in_use_by_oneview.return_value = False

        class OneViewDriverDeploy(deploy.OneViewPeriodicTasks):
            oneview_driver = 'fake_oneview'

        oneview_driver_deploy = OneViewDriverDeploy()
        oneview_driver_deploy._periodic_check_nodes_freed_by_oneview(
            manager, self.context
        )
        self.assertTrue(manager.update_node.called)
        self.assertTrue(manager.do_provisioning_action.called)
        self.assertFalse(self.node.maintenance)
        self.assertIsNone(self.node.maintenance_reason)

    @mock.patch.object(objects.Node, 'get')
    def test__periodic_check_nodes_taken_on_cleanfail(
        self, mock_get_node, mock_get_ov_client
    ):

        driver_internal_info = {
            'oneview_error': common.SERVER_HARDWARE_ALLOCATION_ERROR
        }

        manager = mock.MagicMock(
            spec=['iter_nodes', 'update_node', 'do_provisioning_action']
        )

        manager.iter_nodes.return_value = [
            (self.node.uuid, 'fake_oneview', driver_internal_info)
        ]

        self.node.driver_internal_info = driver_internal_info
        mock_get_node.return_value = self.node

        class OneViewDriverDeploy(deploy.OneViewPeriodicTasks):
            oneview_driver = 'fake_oneview'

        oneview_driver_deploy = OneViewDriverDeploy()
        oneview_driver_deploy._periodic_check_nodes_taken_on_cleanfail(
            manager, self.context
        )
        self.assertTrue(manager.update_node.called)
        self.assertTrue(manager.do_provisioning_action.called)
        self.assertTrue(self.node.maintenance)
        self.assertEqual(common.NODE_IN_USE_BY_ONEVIEW,
                         self.node.maintenance_reason)
        self.assertEqual({}, self.node.driver_internal_info)
