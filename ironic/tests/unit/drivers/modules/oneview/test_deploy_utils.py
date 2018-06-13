# Copyright (2015-2017) Hewlett Packard Enterprise Development LP
# Copyright (2015-2017) Universidade Federal de Campina Grande
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

from ironic.common import exception
from ironic.common import states
from ironic.conductor import task_manager
from ironic.drivers.modules.oneview import common
from ironic.drivers.modules.oneview import deploy_utils
from ironic import objects
from ironic.tests.unit.drivers.modules.oneview import test_common

oneview_models = importutils.try_import('oneview_client.models')


@mock.patch.object(common, 'get_hponeview_client')
class OneViewDeployUtilsTestCase(test_common.BaseOneViewTest):

    def setUp(self):
        super(OneViewDeployUtilsTestCase, self).setUp()
        self.config(manager_url='https://1.2.3.4', group='oneview')
        self.config(username='user', group='oneview')
        self.config(password='password', group='oneview')
        self.info = common.get_oneview_info(self.node)
        deploy_utils.is_node_in_use_by_oneview = mock.Mock(return_value=False)
        deploy_utils.is_node_in_use_by_ironic = mock.Mock(return_value=True)

    # Tests for prepare
    def test_prepare_node_is_in_use_by_oneview(self, mock_oneview_client):
        """`prepare` behavior when the node has a Profile on OneView."""
        deploy_utils.is_node_in_use_by_oneview.return_value = True
        with task_manager.acquire(self.context, self.node.uuid) as task:
            task.node.provision_state = states.DEPLOYING
            self.assertRaises(
                exception.InstanceDeployFailure,
                deploy_utils.prepare,
                task
            )

    @mock.patch.object(objects.Node, 'save')
    def test_prepare_node_is_successfuly_allocated_to_ironic(
            self, mock_save, mock_oneview_client):
        """`prepare` behavior when the node is free from OneView standpoint."""
        with task_manager.acquire(self.context, self.node.uuid) as task:
            task.node.provision_state = states.DEPLOYING
            deploy_utils.prepare(task)
            self.assertTrue(mock_save.called)

    # Tests for tear_down
    def test_tear_down(self, mock_oneview_client):
        """`tear_down` behavior when node already has Profile applied."""
        oneview_client = mock_oneview_client()
        with task_manager.acquire(self.context, self.node.uuid) as task:
            task.node.driver_info['applied_server_profile_uri'] = (
                '/rest/server-profiles/1234556789'
            )
            self.assertTrue(
                'applied_server_profile_uri' in task.node.driver_info
            )
            deploy_utils.tear_down(task)
            self.assertFalse(
                'applied_server_profile_uri' in task.node.driver_info
            )
            self.assertTrue(oneview_client.server_profiles.delete.called)

    # Tests for prepare_cleaning
    @mock.patch.object(objects.Node, 'save')
    def test_prepare_cleaning_when_node_does_not_have_sp_applied(
            self, mock_save, mock_oneview_client):
        """`prepare_cleaning` behavior when node is free."""
        with task_manager.acquire(self.context, self.node.uuid) as task:
            self.assertFalse(
                'applied_server_profile_uri' in task.node.driver_info
            )
            deploy_utils.prepare_cleaning(task)
            self.assertTrue(
                'applied_server_profile_uri' in task.node.driver_info
            )

    @mock.patch.object(objects.Node, 'save')
    def test_prepare_cleaning_when_node_has_sp_applied(
            self, mock_node_save, mock_oneview_client):
        """`prepare_cleaning` behavior when node has Profile applied."""
        oneview_client = mock_oneview_client()
        oneview_client.server_hardware.get.return_value = {
            'serverProfileUri': 'same/sp_applied'
        }
        with task_manager.acquire(self.context, self.node.uuid) as task:
            task.node.driver_info['applied_server_profile_uri'] = (
                'same/sp_applied'
            )
            deploy_utils.prepare_cleaning(task)
            self.assertFalse(mock_node_save.called)

    def test_prepare_cleaning_node_is_in_use_by_oneview(
            self, mock_oneview_client):
        """`prepare_cleaning` behavior when node has Profile on OneView."""
        deploy_utils.is_node_in_use_by_oneview.return_value = True

        with task_manager.acquire(self.context, self.node.uuid) as task:
            self.assertRaises(
                exception.NodeCleaningFailure,
                deploy_utils.prepare_cleaning,
                task
            )

    # Tests for tear_down_cleaning
    def test_tear_down_cleaning(self, mock_oneview_client):
        """Check if Server Profile was deleted and its uri removed."""
        oneview_client = mock_oneview_client()
        with task_manager.acquire(self.context, self.node.uuid) as task:
            task.node.driver_info['applied_server_profile_uri'] = (
                '/rest/server-profiles/1234556789'
            )
            self.assertTrue(
                'applied_server_profile_uri' in task.node.driver_info
            )
            deploy_utils.tear_down_cleaning(task)
            self.assertFalse(
                'applied_server_profile_uri' in task.node.driver_info
            )
            self.assertTrue(oneview_client.server_profiles.delete.called)

    # Tests for is_node_in_use_by_oneview
    def test_is_node_in_use_by_oneview(self, mock_oneview_client):
        """Node has a Server Profile applied by a third party user."""
        server_hardware = {
            'serverProfileUri': '/rest/server-profile/123456789'
        }
        with task_manager.acquire(self.context, self.node.uuid) as task:
            task.node.driver_info['applied_server_profile_uri'] = (
                '/rest/server-profile/987654321'
            )
            self.assertTrue(
                deploy_utils._is_node_in_use(
                    server_hardware,
                    task.node.driver_info['applied_server_profile_uri'],
                    by_oneview=True
                )
            )

    def test_is_node_in_use_by_oneview_no_server_profile(
            self, mock_oneview_client):
        """Node has no Server Profile."""
        server_hardware = {'serverProfileUri': None}
        with task_manager.acquire(self.context, self.node.uuid) as task:
            task.node.driver_info['applied_server_profile_uri'] = (
                '/rest/server-profile/123456789'
            )
            self.assertFalse(
                deploy_utils._is_node_in_use(
                    server_hardware,
                    task.node.driver_info['applied_server_profile_uri'],
                    by_oneview=True
                )
            )

    def test_is_node_in_use_by_oneview_same_server_profile_applied(
            self, mock_oneview_client):
        """Check if node's Server Profile uri is the same applied by ironic."""
        server_hardware = {
            'serverProfileUri': '/rest/server-profile/123456789'
        }
        with task_manager.acquire(self.context, self.node.uuid) as task:
            task.node.driver_info['applied_server_profile_uri'] = (
                '/rest/server-profile/123456789'
            )
            self.assertFalse(
                deploy_utils._is_node_in_use(
                    server_hardware,
                    task.node.driver_info['applied_server_profile_uri'],
                    by_oneview=True
                )
            )

    # Tests for is_node_in_use_by_ironic
    def test_is_node_in_use_by_ironic(self, mock_oneview_client):
        """Node has a Server Profile applied by ironic."""
        server_hardware = {'serverProfileUri': 'same/applied_sp_uri/'}
        with task_manager.acquire(self.context, self.node.uuid) as task:
            task.node.driver_info['applied_server_profile_uri'] = (
                'same/applied_sp_uri/'
            )
            self.assertTrue(
                deploy_utils._is_node_in_use(
                    server_hardware,
                    task.node.driver_info['applied_server_profile_uri'],
                    by_oneview=False
                )
            )

    def test_is_node_in_use_by_ironic_no_server_profile(
            self, mock_oneview_client):
        """Node has no Server Profile."""
        server_hardware = {'serverProfileUri': None}
        with task_manager.acquire(self.context, self.node.uuid) as task:
            task.node.driver_info['applied_server_profile_uri'] = (
                '/applied_sp_uri/'
            )
            self.assertFalse(
                deploy_utils._is_node_in_use(
                    server_hardware,
                    task.node.driver_info['applied_server_profile_uri'],
                    by_oneview=False
                )
            )

    def test__create_profile_from_template(self, mock_oneview_client):
        """Check if the server_profile was created from template."""
        server_hardware_uri = "server_hardware/12456789"
        sp_template_uri = "server_profile_template_uri/13245798"
        oneview_client = mock_oneview_client()
        oneview_client.server_profile_templates.\
            get_new_profile.return_value = {}
        server_profile = {"name": "server_profile_name",
                          "serverHardwareUri": server_hardware_uri,
                          "serverProfileTemplateUri": ""}
        deploy_utils._create_profile_from_template(
            oneview_client,
            "server_profile_name",
            server_hardware_uri,
            sp_template_uri
        )
        oneview_client.server_profiles.create.assert_called_with(
            server_profile)

    # Tests for _add_applied_server_profile_uri_field
    @mock.patch.object(objects.Node, 'save')
    def test__add_applied_server_profile_uri_field(
            self, save, mock_oneview_client):
        """Check if applied_server_profile_uri was added to driver_info."""
        server_profile = {'uri': 'any/applied_sp_uri/'}
        with task_manager.acquire(self.context, self.node.uuid) as task:
            task.node.driver_info.pop('applied_server_profile_uri', None)
            self.assertNotIn(
                'applied_server_profile_uri', task.node.driver_info
            )
            deploy_utils._add_applied_server_profile_uri_field(
                task.node,
                server_profile
            )
            self.assertIn('applied_server_profile_uri', task.node.driver_info)

    # Tests for _del_applied_server_profile_uri_field
    @mock.patch.object(objects.Node, 'save')
    def test__del_applied_server_profile_uri_field(
            self, save, mock_oneview_client):
        """Check if applied_server_profile_uri was removed from driver_info."""
        with task_manager.acquire(self.context, self.node.uuid) as task:
            task.node.driver_info['applied_server_profile_uri'] = (
                'any/applied_sp_uri/'
            )
            self.assertIn('applied_server_profile_uri', task.node.driver_info)
            deploy_utils._del_applied_server_profile_uri_field(task.node)
            self.assertNotIn(
                'applied_server_profile_uri', task.node.driver_info
            )

    # Tests for allocate_server_hardware_to_ironic
    @mock.patch.object(objects.Node, 'save')
    def test_allocate_server_hardware_to_ironic(
            self, mock_node_save, mock_oneview_client):
        """Check if a Profile was created and its uri is in driver_info."""
        oneview_client = mock_oneview_client()
        server_hardware = {'serverProfileUri': None}
        oneview_client.server_hardware.get.return_value = server_hardware

        with task_manager.acquire(self.context, self.node.uuid) as task:
            deploy_utils.allocate_server_hardware_to_ironic(
                task.node, 'serverProfileName'
            )
            self.assertTrue(mock_node_save.called)
            self.assertIn('applied_server_profile_uri', task.node.driver_info)

    @mock.patch.object(objects.Node, 'save')
    def test_allocate_server_hardware_to_ironic_node_has_server_profile(
            self, mock_node_save, mock_oneview_client):
        """Test profile allocation when applied_server_profile_uri exists.

        This test consider that no Server Profile is applied on the Server
        Hardware but the applied_server_profile_uri remained on the node. Thus,
        the conductor should remove the value and apply a new server profile to
        use the node.
        """
        oneview_client = mock_oneview_client()
        server_hardware = {'serverProfileUri': None}
        oneview_client.server_hardware.get.return_value = server_hardware

        with task_manager.acquire(self.context, self.node.uuid) as task:
            task.node.driver_info['applied_server_profile_uri'] = (
                'any/applied_sp_uri/'
            )
            deploy_utils.allocate_server_hardware_to_ironic(
                task.node, 'serverProfileName'
            )
            self.assertTrue(mock_node_save.called)

    # Tests for deallocate_server_hardware_from_ironic
    @mock.patch.object(objects.Node, 'save')
    def test_deallocate_server_hardware_from_ironic(
            self, mock_node_save, mock_oneview_client):
        oneview_client = mock_oneview_client()
        server_hardware = {'serverProfileUri': 'any/applied_sp_uri/'}
        oneview_client.server_hardware.get.return_value = server_hardware
        with task_manager.acquire(self.context, self.node.uuid) as task:
            task.node.driver_info['applied_server_profile_uri'] = (
                'any/applied_sp_uri/'
            )
            deploy_utils.deallocate_server_hardware_from_ironic(task)
            self.assertTrue(mock_node_save.called)
            self.assertTrue(
                'applied_server_profile_uri' not in task.node.driver_info
            )
