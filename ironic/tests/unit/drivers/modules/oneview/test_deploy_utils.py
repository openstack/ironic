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
from ironic.common import exception
from ironic.common import states
from ironic.conductor import task_manager
from ironic.drivers.modules.oneview import common
from ironic.drivers.modules.oneview import deploy_utils
from ironic import objects
from ironic.tests.unit.conductor import mgr_utils
from ironic.tests.unit.db import base as db_base
from ironic.tests.unit.db import utils as db_utils
from ironic.tests.unit.objects import utils as obj_utils

oneview_models = importutils.try_import('oneview_client.models')


@mock.patch.object(common, 'get_oneview_client', spec_set=True, autospec=True)
class OneViewDeployUtilsTestCase(db_base.DbTestCase):

    def setUp(self):
        super(OneViewDeployUtilsTestCase, self).setUp()
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

    # Tests for prepare
    def test_prepare_node_is_in_use_by_oneview(self, mock_get_ov_client):
        """`prepare` behavior when the node already has a Profile on OneView.

        """
        oneview_client = mock_get_ov_client()

        fake_server_hardware = oneview_models.ServerHardware()
        fake_server_hardware.server_profile_uri = "/any/sp_uri"
        oneview_client.get_server_hardware.return_value = fake_server_hardware

        with task_manager.acquire(self.context, self.node.uuid) as task:
            driver_info = task.node.driver_info
            task.node.driver_info = driver_info
            task.node.provision_state = states.DEPLOYING
            self.assertRaises(
                exception.InstanceDeployFailure,
                deploy_utils.prepare,
                oneview_client,
                task
            )

    @mock.patch.object(objects.Node, 'save')
    def test_prepare_node_is_successfuly_allocated_to_ironic(
        self, mock_node_save, mock_get_ov_client
    ):
        """`prepare` behavior when the node is free from OneView standpoint.

        """
        oneview_client = mock_get_ov_client()

        fake_sh = oneview_models.ServerHardware()
        fake_sh.server_profile_uri = None
        oneview_client.get_server_hardware_by_uuid.return_value = fake_sh
        with task_manager.acquire(self.context, self.node.uuid) as task:
            task.node.provision_state = states.DEPLOYING
            deploy_utils.prepare(oneview_client, task)
            self.assertTrue(oneview_client.clone_template_and_apply.called)
            self.assertTrue(oneview_client.get_server_profile_from_hardware)

    # Tests for tear_down
    def test_tear_down(self, mock_get_ov_client):
        """`tear_down` behavior when node already has Profile applied

        """
        sp_uri = '/rest/server-profiles/1234556789'
        ov_client = mock_get_ov_client()
        fake_sh = oneview_models.ServerHardware()
        fake_sh.server_profile_uri = sp_uri
        ov_client = mock_get_ov_client.return_value
        ov_client.get_server_hardware_by_uuid.return_value = fake_sh

        with task_manager.acquire(self.context, self.node.uuid) as task:
            driver_info = task.node.driver_info
            driver_info['applied_server_profile_uri'] = \
                '/rest/server-profiles/1234556789'
            task.node.driver_info = driver_info

            self.assertIn(
                'applied_server_profile_uri', task.node.driver_info
            )
            deploy_utils.tear_down(ov_client, task)
            self.assertNotIn(
                'applied_server_profile_uri', task.node.driver_info
            )
        self.assertTrue(
            ov_client.delete_server_profile.called
        )

    # Tests for prepare_cleaning
    @mock.patch.object(objects.Node, 'save')
    def test_prepare_cleaning_when_node_does_not_have_sp_applied(
        self, mock_node_save, mock_get_ov_client
    ):
        """`prepare_cleaning` behavior when node is free

        """
        oneview_client = mock_get_ov_client()

        fake_sh = oneview_models.ServerHardware()
        fake_sh.server_profile_uri = None
        oneview_client.get_server_hardware_by_uuid.return_value = fake_sh
        with task_manager.acquire(self.context, self.node.uuid) as task:
            deploy_utils.prepare_cleaning(oneview_client, task)
            self.assertTrue(oneview_client.clone_template_and_apply.called)

    @mock.patch.object(objects.Node, 'save')
    def test_prepare_cleaning_when_node_has_sp_applied(
        self, mock_node_save, mock_get_ov_client
    ):
        """`prepare_cleaning` behavior when node already has Profile applied

        """
        oneview_client = mock_get_ov_client()

        fake_sh = oneview_models.ServerHardware()
        fake_sh.server_profile_uri = 'same/sp_applied'
        oneview_client.get_server_hardware_by_uuid.return_value = fake_sh

        with task_manager.acquire(self.context, self.node.uuid) as task:
            driver_info = task.node.driver_info
            driver_info['applied_server_profile_uri'] = 'same/sp_applied'
            task.node.driver_info = driver_info

            deploy_utils.prepare_cleaning(oneview_client, task)
            self.assertFalse(oneview_client.clone_template_and_apply.called)

    def test_prepare_cleaning_node_is_in_use_by_oneview(
        self, mock_get_ov_client
    ):
        """`prepare_cleaning` behavior when node has Server Profile on OneView

        """
        oneview_client = mock_get_ov_client()

        fake_server_hardware = oneview_models.ServerHardware()
        fake_server_hardware.server_profile_uri = "/any/sp_uri"
        oneview_client.get_server_hardware.return_value = fake_server_hardware

        with task_manager.acquire(self.context, self.node.uuid) as task:
            driver_info = task.node.driver_info
            task.node.driver_info = driver_info
            task.node.provision_state = states.DEPLOYING
            self.assertRaises(
                exception.NodeCleaningFailure,
                deploy_utils.prepare_cleaning,
                oneview_client,
                task
            )

    # Tests for tear_down_cleaning
    def test_tear_down_cleaning(self, mock_get_ov_client):
        """Checks if Server Profile was deleted and its uri removed

        """
        sp_uri = '/rest/server-profiles/1234556789'
        ov_client = mock_get_ov_client()
        fake_sh = oneview_models.ServerHardware()
        fake_sh.server_profile_uri = sp_uri
        ov_client = mock_get_ov_client.return_value
        ov_client.get_server_hardware_by_uuid.return_value = fake_sh

        with task_manager.acquire(self.context, self.node.uuid) as task:
            driver_info = task.node.driver_info
            driver_info['applied_server_profile_uri'] = \
                '/rest/server-profiles/1234556789'
            task.node.driver_info = driver_info

            self.assertIn('applied_server_profile_uri', task.node.driver_info)
            deploy_utils.tear_down_cleaning(ov_client, task)
            self.assertNotIn('applied_server_profile_uri',
                             task.node.driver_info)
            self.assertTrue(ov_client.delete_server_profile.called)

    # Tests for is_node_in_use_by_oneview
    def test_is_node_in_use_by_oneview(self, mock_get_ov_client):
        """Node has a Server Profile applied by a third party user.

        """
        oneview_client = mock_get_ov_client()

        fake_server_hardware = oneview_models.ServerHardware()
        fake_server_hardware.server_profile_uri = "/any/sp_uri"

        with task_manager.acquire(self.context, self.node.uuid) as task:
            driver_info = task.node.driver_info
            task.node.driver_info = driver_info
            self.assertTrue(
                deploy_utils.is_node_in_use_by_oneview(oneview_client,
                                                       task.node)
            )

    def test_is_node_in_use_by_oneview_no_server_profile(
        self, mock_get_ov_client
    ):
        """Node has no Server Profile.

        """
        oneview_client = mock_get_ov_client()

        fake_sh = oneview_models.ServerHardware()
        fake_sh.server_profile_uri = None
        oneview_client.get_server_hardware_by_uuid.return_value = fake_sh
        with task_manager.acquire(self.context, self.node.uuid) as task:
            self.assertFalse(
                deploy_utils.is_node_in_use_by_oneview(oneview_client,
                                                       task.node)
            )

    def test_is_node_in_use_by_oneview_same_server_profile_applied(
        self, mock_get_ov_client
    ):
        """Node's Server Profile uri is the same applied by ironic.

        """
        oneview_client = mock_get_ov_client()

        fake_sh = oneview_models.ServerHardware()
        fake_sh.server_profile_uri = 'same/applied_sp_uri/'
        oneview_client.get_server_hardware_by_uuid.return_value = fake_sh

        with task_manager.acquire(self.context, self.node.uuid) as task:
            driver_info = task.node.driver_info
            driver_info['applied_server_profile_uri'] = 'same/applied_sp_uri/'
            task.node.driver_info = driver_info
            self.assertFalse(
                deploy_utils.is_node_in_use_by_oneview(oneview_client,
                                                       task.node)
            )

    # Tests for is_node_in_use_by_ironic
    def test_is_node_in_use_by_ironic(self, mock_get_ov_client):
        """Node has a Server Profile applied by ironic.

        """
        fake_sh = oneview_models.ServerHardware()
        fake_sh.server_profile_uri = "same/applied_sp_uri/"

        ov_client = mock_get_ov_client.return_value
        ov_client.get_server_hardware_by_uuid.return_value = fake_sh

        with task_manager.acquire(self.context, self.node.uuid) as task:
            driver_info = task.node.driver_info
            driver_info['applied_server_profile_uri'] = 'same/applied_sp_uri/'
            task.node.driver_info = driver_info
            self.assertTrue(
                deploy_utils.is_node_in_use_by_ironic(ov_client, task.node)
            )

    def test_is_node_in_use_by_ironic_no_server_profile(
        self, mock_get_ov_client
    ):
        """Node has no Server Profile.

        """
        fake_sh = oneview_models.ServerHardware()
        fake_sh.server_profile_uri = None

        ov_client = mock_get_ov_client.return_value
        ov_client.get_server_hardware_by_uuid.return_value = fake_sh

        with task_manager.acquire(self.context, self.node.uuid) as task:
            self.assertFalse(
                deploy_utils.is_node_in_use_by_ironic(ov_client, task.node)
            )

    # Tests for _add_applied_server_profile_uri_field
    def test__add_applied_server_profile_uri_field(self, mock_get_ov_client):
        """Checks if applied_server_profile_uri was added to driver_info.

        """
        with task_manager.acquire(self.context, self.node.uuid) as task:
            driver_info = task.node.driver_info
            task.node.driver_info = driver_info
            fake_server_profile = oneview_models.ServerProfile()
            fake_server_profile.uri = 'any/applied_sp_uri/'

            self.assertNotIn('applied_server_profile_uri',
                             task.node.driver_info)
            deploy_utils._add_applied_server_profile_uri_field(
                task.node,
                fake_server_profile
            )
            self.assertIn('applied_server_profile_uri', task.node.driver_info)

    # Tests for _del_applied_server_profile_uri_field
    def test__del_applied_server_profile_uri_field(self, mock_get_ov_client):
        """Checks if applied_server_profile_uri was removed from driver_info.

        """
        with task_manager.acquire(self.context, self.node.uuid) as task:
            driver_info = task.node.driver_info
            driver_info['applied_server_profile_uri'] = 'any/applied_sp_uri/'
            task.node.driver_info = driver_info

            self.assertIn('applied_server_profile_uri', task.node.driver_info)
            deploy_utils._del_applied_server_profile_uri_field(task.node)
            self.assertNotIn('applied_server_profile_uri',
                             task.node.driver_info)

    # Tests for allocate_server_hardware_to_ironic
    @mock.patch.object(objects.Node, 'save')
    def test_allocate_server_hardware_to_ironic(
        self, mock_node_save, mock_get_ov_client
    ):
        """Checks if a Server Profile was created and its uri is in driver_info.

        """
        oneview_client = mock_get_ov_client()

        fake_sh = oneview_models.ServerHardware()
        fake_sh.server_profile_uri = None
        oneview_client.get_server_hardware_by_uuid.return_value = fake_sh

        with task_manager.acquire(self.context, self.node.uuid) as task:
            deploy_utils.allocate_server_hardware_to_ironic(
                oneview_client, task.node, 'serverProfileName'
            )
            self.assertTrue(oneview_client.clone_template_and_apply.called)
            self.assertIn('applied_server_profile_uri', task.node.driver_info)

    @mock.patch.object(objects.Node, 'save')
    @mock.patch.object(deploy_utils,
                       '_del_applied_server_profile_uri_field')
    def test_allocate_server_hardware_to_ironic_node_has_server_profile(
        self, mock_delete_applied_sp, mock_node_save, mock_get_ov_client
    ):
        """Tests server profile allocation when applied_server_profile_uri exists.

        This test consider that no Server Profile is applied on the Server
        Hardware but the applied_server_profile_uri remained on the node. Thus,
        the conductor should remove the value and apply a new server profile to
        use the node.
        """
        oneview_client = mock_get_ov_client()

        fake_sh = oneview_models.ServerHardware()
        fake_sh.server_profile_uri = None
        oneview_client.get_server_hardware_by_uuid.return_value = fake_sh

        with task_manager.acquire(self.context, self.node.uuid) as task:
            driver_info = task.node.driver_info
            driver_info['applied_server_profile_uri'] = 'any/applied_sp_uri/'
            task.node.driver_info = driver_info

            deploy_utils.allocate_server_hardware_to_ironic(
                oneview_client, task.node, 'serverProfileName'
            )
            self.assertTrue(mock_delete_applied_sp.called)

    # Tests for deallocate_server_hardware_from_ironic
    @mock.patch.object(objects.Node, 'save')
    def test_deallocate_server_hardware_from_ironic(
        self, mock_node_save, mock_get_ov_client
    ):
        oneview_client = mock_get_ov_client()

        fake_sh = oneview_models.ServerHardware()
        fake_sh.server_profile_uri = 'any/applied_sp_uri/'
        oneview_client.get_server_hardware_by_uuid.return_value = fake_sh
        mock_get_ov_client.return_value = oneview_client

        with task_manager.acquire(self.context, self.node.uuid) as task:
            driver_info = task.node.driver_info
            driver_info['applied_server_profile_uri'] = 'any/applied_sp_uri/'
            task.node.driver_info = driver_info

            deploy_utils.deallocate_server_hardware_from_ironic(
                oneview_client, task.node
            )
            self.assertTrue(oneview_client.delete_server_profile.called)
            self.assertNotIn(
                'applied_server_profile_uri', task.node.driver_info
            )

    @mock.patch.object(objects.Node, 'save')
    def test_deallocate_server_hardware_from_ironic_missing_profile_uuid(
        self, mock_node_save, mock_get_ov_client
    ):
        """Test for case when server profile application fails.

        Due to an error when applying Server Profile in OneView,
        the node will have no Server Profile uuid in the
        'applied_server_profile_uri' namespace. When the method
        tested is called without Server Profile uuid, the client
        will raise a ValueError when trying to delete the profile,
        this error is converted to an OneViewError.
        """

        ov_client = mock_get_ov_client.return_value
        fake_sh = oneview_models.ServerHardware()
        fake_sh.server_profile_uri = 'any/applied_sp_uri/'
        ov_client.get_server_hardware_by_uuid.return_value = fake_sh
        ov_client.delete_server_profile.side_effect = ValueError
        mock_get_ov_client.return_value = ov_client

        with task_manager.acquire(self.context, self.node.uuid) as task:
            driver_info = task.node.driver_info
            driver_info['applied_server_profile_uri'] = 'any/applied_sp_uri/'
            task.node.driver_info = driver_info
            self.assertRaises(
                exception.OneViewError,
                deploy_utils.deallocate_server_hardware_from_ironic,
                ov_client,
                task.node
            )
            self.assertTrue(ov_client.delete_server_profile.called)
            self.assertIn(
                'applied_server_profile_uri', task.node.driver_info
            )
