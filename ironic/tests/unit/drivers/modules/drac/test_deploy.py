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
Test class for DRAC deploy interface
"""

import mock

from ironic.common import states
from ironic.conductor import task_manager
from ironic.drivers.modules import deploy_utils
from ironic.tests.unit.conductor import mgr_utils
from ironic.tests.unit.db import base as db_base
from ironic.tests.unit.db import utils as db_utils
from ironic.tests.unit.objects import utils as obj_utils

INFO_DICT = db_utils.get_test_drac_info()


class DracDeployTestCase(db_base.DbTestCase):

    def setUp(self):
        super(DracDeployTestCase, self).setUp()
        mgr_utils.mock_the_extension_manager(driver='fake_drac')
        self.node = obj_utils.create_test_node(self.context,
                                               driver='fake_drac',
                                               driver_info=INFO_DICT)

    @mock.patch.object(deploy_utils, 'prepare_inband_cleaning', spec_set=True,
                       autospec=True)
    def test_prepare_cleaning_with_no_clean_step(
            self, mock_prepare_inband_cleaning):
        mock_prepare_inband_cleaning.return_value = states.CLEANWAIT

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            res = task.driver.deploy.prepare_cleaning(task)
            self.assertEqual(states.CLEANWAIT, res)

        mock_prepare_inband_cleaning.assert_called_once_with(
            task, manage_boot=True)

    @mock.patch.object(deploy_utils, 'prepare_inband_cleaning', spec_set=True,
                       autospec=True)
    def test_prepare_cleaning_with_inband_clean_step(
            self, mock_prepare_inband_cleaning):
        self.node.driver_internal_info['clean_steps'] = [
            {'step': 'erase_disks', 'priority': 20, 'interface': 'deploy'}]
        mock_prepare_inband_cleaning.return_value = states.CLEANWAIT

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            res = task.driver.deploy.prepare_cleaning(task)
            self.assertEqual(states.CLEANWAIT, res)

        mock_prepare_inband_cleaning.assert_called_once_with(
            task, manage_boot=True)

    @mock.patch.object(deploy_utils, 'prepare_inband_cleaning', spec_set=True,
                       autospec=True)
    def test_prepare_cleaning_with_oob_clean_step_with_no_agent_cached_steps(
            self, mock_prepare_inband_cleaning):
        self.node.driver_internal_info['clean_steps'] = [
            {'interface': 'raid', 'step': 'create_configuration'}]
        mock_prepare_inband_cleaning.return_value = states.CLEANWAIT

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            res = task.driver.deploy.prepare_cleaning(task)
            self.assertEqual(states.CLEANWAIT, res)

        mock_prepare_inband_cleaning.assert_called_once_with(
            task, manage_boot=True)

    @mock.patch.object(deploy_utils, 'prepare_inband_cleaning', spec_set=True,
                       autospec=True)
    def test_prepare_cleaning_with_oob_clean_step_with_agent_cached_steps(
            self, mock_prepare_inband_cleaning):
        self.node.driver_internal_info['agent_cached_clean_steps'] = []
        self.node.driver_internal_info['clean_steps'] = [
            {'interface': 'raid', 'step': 'create_configuration'}]
        mock_prepare_inband_cleaning.return_value = states.CLEANWAIT

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            res = task.driver.deploy.prepare_cleaning(task)
            self.assertEqual(states.CLEANWAIT, res)

        mock_prepare_inband_cleaning.assert_called_once_with(
            task, manage_boot=True)
