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

from oslo_config import cfg
from oslo_utils import uuidutils

from ironic.common import exception
from ironic.common import states
from ironic.conductor import steps as conductor_steps
from ironic.conductor import task_manager
from ironic import objects
from ironic.tests.unit.db import base as db_base
from ironic.tests.unit.db import utils as db_utils
from ironic.tests.unit.objects import utils as obj_utils

CONF = cfg.CONF


class NodeDeployStepsTestCase(db_base.DbTestCase):
    def setUp(self):
        super(NodeDeployStepsTestCase, self).setUp()

        self.deploy_start = {
            'step': 'deploy_start', 'priority': 50, 'interface': 'deploy'}
        self.power_one = {
            'step': 'power_one', 'priority': 40, 'interface': 'power'}
        self.deploy_middle = {
            'step': 'deploy_middle', 'priority': 40, 'interface': 'deploy'}
        self.deploy_end = {
            'step': 'deploy_end', 'priority': 20, 'interface': 'deploy'}
        self.power_disable = {
            'step': 'power_disable', 'priority': 0, 'interface': 'power'}
        self.deploy_core = {
            'step': 'deploy', 'priority': 100, 'interface': 'deploy'}
        # enabled steps
        self.deploy_steps = [self.deploy_start, self.power_one,
                             self.deploy_middle, self.deploy_end]
        # Deploy step with argsinfo.
        self.deploy_raid = {
            'step': 'build_raid', 'priority': 0, 'interface': 'deploy',
            'argsinfo': {'arg1': {'description': 'desc1', 'required': True},
                         'arg2': {'description': 'desc2'}}}
        self.node = obj_utils.create_test_node(
            self.context, driver='fake-hardware')

    @mock.patch('ironic.drivers.modules.fake.FakeDeploy.get_deploy_steps',
                autospec=True)
    @mock.patch('ironic.drivers.modules.fake.FakePower.get_deploy_steps',
                autospec=True)
    @mock.patch('ironic.drivers.modules.fake.FakeManagement.get_deploy_steps',
                autospec=True)
    def test__get_deployment_steps(self, mock_mgt_steps, mock_power_steps,
                                   mock_deploy_steps):
        # Test getting deploy steps, with one driver returning None, two
        # conflicting priorities, and asserting they are ordered properly.

        mock_power_steps.return_value = [self.power_disable, self.power_one]
        mock_deploy_steps.return_value = [
            self.deploy_start, self.deploy_middle, self.deploy_end]

        expected = self.deploy_steps + [self.power_disable]
        with task_manager.acquire(
                self.context, self.node.uuid, shared=False) as task:
            steps = conductor_steps._get_deployment_steps(task, enabled=False)

            self.assertEqual(expected, steps)
            mock_mgt_steps.assert_called_once_with(mock.ANY, task)
            mock_power_steps.assert_called_once_with(mock.ANY, task)
            mock_deploy_steps.assert_called_once_with(mock.ANY, task)

    @mock.patch('ironic.drivers.modules.fake.FakeDeploy.get_deploy_steps',
                autospec=True)
    @mock.patch('ironic.drivers.modules.fake.FakePower.get_deploy_steps',
                autospec=True)
    @mock.patch('ironic.drivers.modules.fake.FakeManagement.get_deploy_steps',
                autospec=True)
    def test__get_deploy_steps_unsorted(self, mock_mgt_steps, mock_power_steps,
                                        mock_deploy_steps):

        mock_deploy_steps.return_value = [self.deploy_end,
                                          self.deploy_start,
                                          self.deploy_middle]
        with task_manager.acquire(
                self.context, self.node.uuid, shared=False) as task:
            steps = conductor_steps._get_deployment_steps(task, enabled=False,
                                                          sort=False)
            self.assertEqual(mock_deploy_steps.return_value, steps)
            mock_mgt_steps.assert_called_once_with(mock.ANY, task)
            mock_power_steps.assert_called_once_with(mock.ANY, task)
            mock_deploy_steps.assert_called_once_with(mock.ANY, task)

    @mock.patch('ironic.drivers.modules.fake.FakeDeploy.get_deploy_steps',
                autospec=True)
    @mock.patch('ironic.drivers.modules.fake.FakePower.get_deploy_steps',
                autospec=True)
    @mock.patch('ironic.drivers.modules.fake.FakeManagement.get_deploy_steps',
                autospec=True)
    def test__get_deployment_steps_only_enabled(
            self, mock_mgt_steps, mock_power_steps, mock_deploy_steps):
        # Test getting only deploy steps, with one driver returning None, two
        # conflicting priorities, and asserting they are ordered properly.
        # Should discard zero-priority deploy step.

        mock_power_steps.return_value = [self.power_one, self.power_disable]
        mock_deploy_steps.return_value = [self.deploy_end,
                                          self.deploy_middle,
                                          self.deploy_start]

        with task_manager.acquire(
                self.context, self.node.uuid, shared=True) as task:
            steps = conductor_steps._get_deployment_steps(task, enabled=True)

            self.assertEqual(self.deploy_steps, steps)
            mock_mgt_steps.assert_called_once_with(mock.ANY, task)
            mock_power_steps.assert_called_once_with(mock.ANY, task)
            mock_deploy_steps.assert_called_once_with(mock.ANY, task)

    @mock.patch.object(objects.DeployTemplate, 'list_by_names')
    def test__get_deployment_templates_no_traits(self, mock_list):
        with task_manager.acquire(
                self.context, self.node.uuid, shared=False) as task:
            templates = conductor_steps._get_deployment_templates(task)
            self.assertEqual([], templates)
            self.assertFalse(mock_list.called)

    @mock.patch.object(objects.DeployTemplate, 'list_by_names')
    def test__get_deployment_templates(self, mock_list):
        traits = ['CUSTOM_DT1', 'CUSTOM_DT2']
        node = obj_utils.create_test_node(
            self.context, uuid=uuidutils.generate_uuid(),
            instance_info={'traits': traits})
        template1 = obj_utils.get_test_deploy_template(self.context)
        template2 = obj_utils.get_test_deploy_template(
            self.context, name='CUSTOM_DT2', uuid=uuidutils.generate_uuid(),
            steps=[{'interface': 'bios', 'step': 'apply_configuration',
                    'args': {}, 'priority': 1}])
        mock_list.return_value = [template1, template2]
        expected = [template1, template2]
        with task_manager.acquire(
                self.context, node.uuid, shared=False) as task:
            templates = conductor_steps._get_deployment_templates(task)
            self.assertEqual(expected, templates)
            mock_list.assert_called_once_with(task.context, traits)

    def test__get_steps_from_deployment_templates(self):
        template1 = obj_utils.get_test_deploy_template(self.context)
        template2 = obj_utils.get_test_deploy_template(
            self.context, name='CUSTOM_DT2', uuid=uuidutils.generate_uuid(),
            steps=[{'interface': 'bios', 'step': 'apply_configuration',
                    'args': {}, 'priority': 1}])
        step1 = template1.steps[0]
        step2 = template2.steps[0]
        expected = [
            {
                'interface': step1['interface'],
                'step': step1['step'],
                'args': step1['args'],
                'priority': step1['priority'],
            },
            {
                'interface': step2['interface'],
                'step': step2['step'],
                'args': step2['args'],
                'priority': step2['priority'],
            }
        ]
        with task_manager.acquire(
                self.context, self.node.uuid, shared=False) as task:
            steps = conductor_steps._get_steps_from_deployment_templates(
                task, [template1, template2])
            self.assertEqual(expected, steps)

    @mock.patch.object(conductor_steps, '_get_validated_steps_from_templates',
                       autospec=True)
    @mock.patch.object(conductor_steps, '_get_deployment_steps', autospec=True)
    def _test__get_all_deployment_steps(self, user_steps, driver_steps,
                                        expected_steps, mock_steps,
                                        mock_validated):
        mock_validated.return_value = user_steps
        mock_steps.return_value = driver_steps

        with task_manager.acquire(
                self.context, self.node.uuid, shared=False) as task:
            steps = conductor_steps._get_all_deployment_steps(task)
            self.assertEqual(expected_steps, steps)
            mock_validated.assert_called_once_with(task, skip_missing=False)
            mock_steps.assert_called_once_with(task, enabled=True, sort=False)

    def test__get_all_deployment_steps_no_steps(self):
        # Nothing in -> nothing out.
        user_steps = []
        driver_steps = []
        expected_steps = []
        self._test__get_all_deployment_steps(user_steps, driver_steps,
                                             expected_steps)

    def test__get_all_deployment_steps_no_user_steps(self):
        # Only driver steps in -> only driver steps out.
        user_steps = []
        driver_steps = self.deploy_steps
        expected_steps = self.deploy_steps
        self._test__get_all_deployment_steps(user_steps, driver_steps,
                                             expected_steps)

    def test__get_all_deployment_steps_no_driver_steps(self):
        # Only user steps in -> only user steps out.
        user_steps = self.deploy_steps
        driver_steps = []
        expected_steps = self.deploy_steps
        self._test__get_all_deployment_steps(user_steps, driver_steps,
                                             expected_steps)

    def test__get_all_deployment_steps_user_and_driver_steps(self):
        # Driver and user steps in -> driver and user steps out.
        user_steps = self.deploy_steps[:2]
        driver_steps = self.deploy_steps[2:]
        expected_steps = self.deploy_steps
        self._test__get_all_deployment_steps(user_steps, driver_steps,
                                             expected_steps)

    @mock.patch.object(conductor_steps, '_get_validated_steps_from_templates',
                       autospec=True)
    @mock.patch.object(conductor_steps, '_get_deployment_steps', autospec=True)
    def test__get_all_deployment_steps_skip_missing(self, mock_steps,
                                                    mock_validated):
        user_steps = self.deploy_steps[:2]
        driver_steps = self.deploy_steps[2:]
        expected_steps = self.deploy_steps
        mock_validated.return_value = user_steps
        mock_steps.return_value = driver_steps

        with task_manager.acquire(
                self.context, self.node.uuid, shared=False) as task:
            steps = conductor_steps._get_all_deployment_steps(
                task, skip_missing=True)
            self.assertEqual(expected_steps, steps)
            mock_validated.assert_called_once_with(task, skip_missing=True)
            mock_steps.assert_called_once_with(task, enabled=True, sort=False)

    def test__get_all_deployment_steps_disable_core_steps(self):
        # User steps can disable core driver steps.
        user_steps = [self.deploy_core.copy()]
        user_steps[0].update({'priority': 0})
        driver_steps = [self.deploy_core]
        expected_steps = []
        self._test__get_all_deployment_steps(user_steps, driver_steps,
                                             expected_steps)

    def test__get_all_deployment_steps_override_driver_steps(self):
        # User steps override non-core driver steps.
        user_steps = [step.copy() for step in self.deploy_steps[:2]]
        user_steps[0].update({'priority': 200})
        user_steps[1].update({'priority': 100})
        driver_steps = self.deploy_steps
        expected_steps = user_steps + self.deploy_steps[2:]
        self._test__get_all_deployment_steps(user_steps, driver_steps,
                                             expected_steps)

    def test__get_all_deployment_steps_duplicate_user_steps(self):
        # Duplicate user steps override non-core driver steps.

        # NOTE(mgoddard): This case is currently prevented by the API and
        # conductor - the interface/step must be unique across all enabled
        # steps. This test ensures that we can support this case, in case we
        # choose to allow it in future.
        user_steps = [self.deploy_start.copy(), self.deploy_start.copy()]
        user_steps[0].update({'priority': 200})
        user_steps[1].update({'priority': 100})
        driver_steps = self.deploy_steps
        # Each user invocation of the deploy_start step should be included, but
        # not the default deploy_start from the driver.
        expected_steps = user_steps + self.deploy_steps[1:]
        self._test__get_all_deployment_steps(user_steps, driver_steps,
                                             expected_steps)

    @mock.patch.object(conductor_steps, '_get_validated_steps_from_templates',
                       autospec=True)
    @mock.patch.object(conductor_steps, '_get_deployment_steps', autospec=True)
    def test__get_all_deployment_steps_error(self, mock_steps, mock_validated):
        mock_validated.side_effect = exception.InvalidParameterValue('foo')

        with task_manager.acquire(
                self.context, self.node.uuid, shared=False) as task:
            self.assertRaises(exception.InvalidParameterValue,
                              conductor_steps._get_all_deployment_steps, task)
            mock_validated.assert_called_once_with(task, skip_missing=False)
            self.assertFalse(mock_steps.called)

    @mock.patch.object(conductor_steps, '_get_all_deployment_steps',
                       autospec=True)
    def test_set_node_deployment_steps(self, mock_steps):
        mock_steps.return_value = self.deploy_steps

        with task_manager.acquire(
                self.context, self.node.uuid, shared=False) as task:
            conductor_steps.set_node_deployment_steps(task)
            self.node.refresh()
            self.assertEqual(self.deploy_steps,
                             self.node.driver_internal_info['deploy_steps'])
            self.assertEqual({}, self.node.deploy_step)
            self.assertIsNone(
                self.node.driver_internal_info['deploy_step_index'])
            mock_steps.assert_called_once_with(task, skip_missing=False)

    @mock.patch.object(conductor_steps, '_get_all_deployment_steps',
                       autospec=True)
    def test_set_node_deployment_steps_skip_missing(self, mock_steps):
        mock_steps.return_value = self.deploy_steps

        with task_manager.acquire(
                self.context, self.node.uuid, shared=False) as task:
            conductor_steps.set_node_deployment_steps(task, skip_missing=True)
            self.node.refresh()
            self.assertEqual(self.deploy_steps,
                             self.node.driver_internal_info['deploy_steps'])
            self.assertEqual({}, self.node.deploy_step)
            self.assertIsNone(
                self.node.driver_internal_info['deploy_step_index'])
            mock_steps.assert_called_once_with(task, skip_missing=True)

    @mock.patch.object(conductor_steps, '_get_deployment_steps', autospec=True)
    def test__validate_user_deploy_steps(self, mock_steps):
        mock_steps.return_value = self.deploy_steps

        user_steps = [{'step': 'deploy_start', 'interface': 'deploy',
                       'priority': 100},
                      {'step': 'power_one', 'interface': 'power',
                       'priority': 200}]

        with task_manager.acquire(self.context, self.node.uuid) as task:
            result = conductor_steps._validate_user_deploy_steps(task,
                                                                 user_steps)
            mock_steps.assert_called_once_with(task, enabled=False, sort=False)

        self.assertEqual(user_steps, result)

    @mock.patch.object(conductor_steps, '_get_deployment_steps', autospec=True)
    def test__validate_user_deploy_steps_no_steps(self, mock_steps):
        mock_steps.return_value = self.deploy_steps

        with task_manager.acquire(self.context, self.node.uuid) as task:
            conductor_steps._validate_user_deploy_steps(task, [])
            mock_steps.assert_called_once_with(task, enabled=False, sort=False)

    @mock.patch.object(conductor_steps, '_get_deployment_steps', autospec=True)
    def test__validate_user_deploy_steps_get_steps_exception(self, mock_steps):
        mock_steps.side_effect = exception.InstanceDeployFailure('bad')

        with task_manager.acquire(self.context, self.node.uuid) as task:
            self.assertRaises(exception.InstanceDeployFailure,
                              conductor_steps._validate_user_deploy_steps,
                              task, [])
            mock_steps.assert_called_once_with(task, enabled=False, sort=False)

    @mock.patch.object(conductor_steps, '_get_deployment_steps', autospec=True)
    def test__validate_user_deploy_steps_not_supported(self, mock_steps):
        mock_steps.return_value = self.deploy_steps
        user_steps = [{'step': 'power_one', 'interface': 'power',
                       'priority': 200},
                      {'step': 'bad_step', 'interface': 'deploy',
                       'priority': 100}]

        with task_manager.acquire(self.context, self.node.uuid) as task:
            self.assertRaisesRegex(exception.InvalidParameterValue,
                                   "does not support.*bad_step",
                                   conductor_steps._validate_user_deploy_steps,
                                   task, user_steps)
            mock_steps.assert_called_once_with(task, enabled=False, sort=False)

    @mock.patch.object(conductor_steps, '_get_deployment_steps', autospec=True)
    def test__validate_user_deploy_steps_skip_missing(self, mock_steps):
        mock_steps.return_value = self.deploy_steps
        user_steps = [{'step': 'power_one', 'interface': 'power',
                       'priority': 200},
                      {'step': 'bad_step', 'interface': 'deploy',
                       'priority': 100}]

        with task_manager.acquire(self.context, self.node.uuid) as task:
            result = conductor_steps._validate_user_deploy_steps(
                task, user_steps, skip_missing=True)
            self.assertEqual(user_steps[:1], result)

    @mock.patch.object(conductor_steps, '_get_deployment_steps', autospec=True)
    def test__validate_user_deploy_steps_invalid_arg(self, mock_steps):
        mock_steps.return_value = self.deploy_steps
        user_steps = [{'step': 'power_one', 'interface': 'power',
                       'args': {'arg1': 'val1', 'arg2': 'val2'},
                       'priority': 200}]

        with task_manager.acquire(self.context, self.node.uuid) as task:
            self.assertRaisesRegex(exception.InvalidParameterValue,
                                   "power_one.*unexpected.*arg1",
                                   conductor_steps._validate_user_deploy_steps,
                                   task, user_steps)
            mock_steps.assert_called_once_with(task, enabled=False, sort=False)

    @mock.patch.object(conductor_steps, '_get_deployment_steps', autospec=True)
    def test__validate_user_deploy_steps_missing_required_arg(self,
                                                              mock_steps):
        mock_steps.return_value = [self.power_one, self.deploy_raid]
        user_steps = [{'step': 'power_one', 'interface': 'power',
                       'priority': 200},
                      {'step': 'build_raid', 'interface': 'deploy',
                       'priority': 100}]

        with task_manager.acquire(self.context, self.node.uuid) as task:
            self.assertRaisesRegex(exception.InvalidParameterValue,
                                   "build_raid.*missing.*arg1",
                                   conductor_steps._validate_user_deploy_steps,
                                   task, user_steps)
            mock_steps.assert_called_once_with(task, enabled=False, sort=False)

    @mock.patch.object(conductor_steps, '_get_deployment_steps', autospec=True)
    def test__validate_user_deploy_steps_disable_non_core(self, mock_steps):
        # Required arguments don't apply to disabled steps.
        mock_steps.return_value = [self.power_one, self.deploy_raid]
        user_steps = [{'step': 'power_one', 'interface': 'power',
                       'priority': 200},
                      {'step': 'build_raid', 'interface': 'deploy',
                       'priority': 0}]

        with task_manager.acquire(self.context, self.node.uuid) as task:
            result = conductor_steps._validate_user_deploy_steps(task,
                                                                 user_steps)
            mock_steps.assert_called_once_with(task, enabled=False, sort=False)

        self.assertEqual(user_steps, result)

    @mock.patch.object(conductor_steps, '_get_deployment_steps', autospec=True)
    def test__validate_user_deploy_steps_disable_core(self, mock_steps):
        mock_steps.return_value = [self.power_one, self.deploy_core]
        user_steps = [{'step': 'power_one', 'interface': 'power',
                       'priority': 200},
                      {'step': 'deploy', 'interface': 'deploy', 'priority': 0}]

        with task_manager.acquire(self.context, self.node.uuid) as task:
            result = conductor_steps._validate_user_deploy_steps(task,
                                                                 user_steps)
            mock_steps.assert_called_once_with(task, enabled=False, sort=False)

        self.assertEqual(user_steps, result)

    @mock.patch.object(conductor_steps, '_get_deployment_steps', autospec=True)
    def test__validate_user_deploy_steps_override_core(self, mock_steps):
        mock_steps.return_value = [self.power_one, self.deploy_core]
        user_steps = [{'step': 'power_one', 'interface': 'power',
                       'priority': 200},
                      {'step': 'deploy', 'interface': 'deploy',
                       'priority': 200}]

        with task_manager.acquire(self.context, self.node.uuid) as task:
            self.assertRaisesRegex(exception.InvalidParameterValue,
                                   "deploy.*is a core step",
                                   conductor_steps._validate_user_deploy_steps,
                                   task, user_steps)
            mock_steps.assert_called_once_with(task, enabled=False, sort=False)

    @mock.patch.object(conductor_steps, '_get_deployment_steps', autospec=True)
    def test__validate_user_deploy_steps_duplicates(self, mock_steps):
        mock_steps.return_value = [self.power_one, self.deploy_core]
        user_steps = [{'step': 'power_one', 'interface': 'power',
                       'priority': 200},
                      {'step': 'power_one', 'interface': 'power',
                       'priority': 100}]

        with task_manager.acquire(self.context, self.node.uuid) as task:
            self.assertRaisesRegex(exception.InvalidParameterValue,
                                   "Duplicate deploy steps for "
                                   "power.power_one",
                                   conductor_steps._validate_user_deploy_steps,
                                   task, user_steps)
            mock_steps.assert_called_once_with(task, enabled=False, sort=False)


class NodeCleaningStepsTestCase(db_base.DbTestCase):
    def setUp(self):
        super(NodeCleaningStepsTestCase, self).setUp()

        self.power_update = {
            'step': 'update_firmware', 'priority': 10, 'interface': 'power'}
        self.deploy_update = {
            'step': 'update_firmware', 'priority': 10, 'interface': 'deploy'}
        self.deploy_erase = {
            'step': 'erase_disks', 'priority': 20, 'interface': 'deploy',
            'abortable': True}
        # Automated cleaning should be executed in this order
        self.clean_steps = [self.deploy_erase, self.power_update,
                            self.deploy_update]
        # Manual clean step
        self.deploy_raid = {
            'step': 'build_raid', 'priority': 0, 'interface': 'deploy',
            'argsinfo': {'arg1': {'description': 'desc1', 'required': True},
                         'arg2': {'description': 'desc2'}}}

    @mock.patch('ironic.drivers.modules.fake.FakeBIOS.get_clean_steps',
                lambda self, task: [])
    @mock.patch('ironic.drivers.modules.fake.FakeDeploy.get_clean_steps')
    @mock.patch('ironic.drivers.modules.fake.FakePower.get_clean_steps')
    def test__get_cleaning_steps(self, mock_power_steps, mock_deploy_steps):
        # Test getting cleaning steps, with one driver returning None, two
        # conflicting priorities, and asserting they are ordered properly.
        node = obj_utils.create_test_node(
            self.context, driver='fake-hardware',
            provision_state=states.CLEANING,
            target_provision_state=states.AVAILABLE)

        mock_power_steps.return_value = [self.power_update]
        mock_deploy_steps.return_value = [self.deploy_erase,
                                          self.deploy_update]

        with task_manager.acquire(
                self.context, node.uuid, shared=False) as task:
            steps = conductor_steps._get_cleaning_steps(task, enabled=False)

        self.assertEqual(self.clean_steps, steps)

    @mock.patch('ironic.drivers.modules.fake.FakeBIOS.get_clean_steps',
                lambda self, task: [])
    @mock.patch('ironic.drivers.modules.fake.FakeDeploy.get_clean_steps')
    @mock.patch('ironic.drivers.modules.fake.FakePower.get_clean_steps')
    def test__get_cleaning_steps_unsorted(self, mock_power_steps,
                                          mock_deploy_steps):
        node = obj_utils.create_test_node(
            self.context, driver='fake-hardware',
            provision_state=states.CLEANING,
            target_provision_state=states.MANAGEABLE)

        mock_deploy_steps.return_value = [self.deploy_raid,
                                          self.deploy_update,
                                          self.deploy_erase]
        with task_manager.acquire(
                self.context, node.uuid, shared=False) as task:
            steps = conductor_steps._get_cleaning_steps(task, enabled=False,
                                                        sort=False)
        self.assertEqual(mock_deploy_steps.return_value, steps)

    @mock.patch('ironic.drivers.modules.fake.FakeDeploy.get_clean_steps')
    @mock.patch('ironic.drivers.modules.fake.FakePower.get_clean_steps')
    def test__get_cleaning_steps_only_enabled(self, mock_power_steps,
                                              mock_deploy_steps):
        # Test getting only cleaning steps, with one driver returning None, two
        # conflicting priorities, and asserting they are ordered properly.
        # Should discard zero-priority (manual) clean step
        node = obj_utils.create_test_node(
            self.context, driver='fake-hardware',
            provision_state=states.CLEANING,
            target_provision_state=states.AVAILABLE)

        mock_power_steps.return_value = [self.power_update]
        mock_deploy_steps.return_value = [self.deploy_erase,
                                          self.deploy_update,
                                          self.deploy_raid]

        with task_manager.acquire(
                self.context, node.uuid, shared=True) as task:
            steps = conductor_steps._get_cleaning_steps(task, enabled=True)

        self.assertEqual(self.clean_steps, steps)

    @mock.patch.object(conductor_steps, '_validate_user_clean_steps')
    @mock.patch.object(conductor_steps, '_get_cleaning_steps')
    def test_set_node_cleaning_steps_automated(self, mock_steps,
                                               mock_validate_user_steps):
        mock_steps.return_value = self.clean_steps

        node = obj_utils.create_test_node(
            self.context, driver='fake-hardware',
            provision_state=states.CLEANING,
            target_provision_state=states.AVAILABLE,
            last_error=None,
            clean_step=None)

        with task_manager.acquire(
                self.context, node.uuid, shared=False) as task:
            conductor_steps.set_node_cleaning_steps(task)
            node.refresh()
            self.assertEqual(self.clean_steps,
                             node.driver_internal_info['clean_steps'])
            self.assertEqual({}, node.clean_step)
            mock_steps.assert_called_once_with(task, enabled=True)
            self.assertFalse(mock_validate_user_steps.called)

    @mock.patch.object(conductor_steps, '_validate_user_clean_steps')
    @mock.patch.object(conductor_steps, '_get_cleaning_steps')
    def test_set_node_cleaning_steps_manual(self, mock_steps,
                                            mock_validate_user_steps):
        clean_steps = [self.deploy_raid]
        mock_steps.return_value = self.clean_steps
        mock_validate_user_steps.return_value = clean_steps

        node = obj_utils.create_test_node(
            self.context, driver='fake-hardware',
            provision_state=states.CLEANING,
            target_provision_state=states.MANAGEABLE,
            last_error=None,
            clean_step=None,
            driver_internal_info={'clean_steps': clean_steps})

        with task_manager.acquire(
                self.context, node.uuid, shared=False) as task:
            conductor_steps.set_node_cleaning_steps(task)
            node.refresh()
            self.assertEqual(clean_steps,
                             node.driver_internal_info['clean_steps'])
            self.assertEqual({}, node.clean_step)
            self.assertFalse(mock_steps.called)
            mock_validate_user_steps.assert_called_once_with(task, clean_steps)

    @mock.patch.object(conductor_steps, '_get_cleaning_steps')
    def test__validate_user_clean_steps(self, mock_steps):
        node = obj_utils.create_test_node(self.context)
        mock_steps.return_value = self.clean_steps

        user_steps = [{'step': 'update_firmware', 'interface': 'power'},
                      {'step': 'erase_disks', 'interface': 'deploy'}]

        with task_manager.acquire(self.context, node.uuid) as task:
            result = conductor_steps._validate_user_clean_steps(task,
                                                                user_steps)
            mock_steps.assert_called_once_with(task, enabled=False, sort=False)

        expected = [{'step': 'update_firmware', 'interface': 'power',
                     'priority': 10, 'abortable': False},
                    {'step': 'erase_disks', 'interface': 'deploy',
                     'priority': 20, 'abortable': True}]
        self.assertEqual(expected, result)

    @mock.patch.object(conductor_steps, '_get_cleaning_steps')
    def test__validate_user_clean_steps_no_steps(self, mock_steps):
        node = obj_utils.create_test_node(self.context)
        mock_steps.return_value = self.clean_steps

        with task_manager.acquire(self.context, node.uuid) as task:
            conductor_steps._validate_user_clean_steps(task, [])
            mock_steps.assert_called_once_with(task, enabled=False, sort=False)

    @mock.patch.object(conductor_steps, '_get_cleaning_steps')
    def test__validate_user_clean_steps_get_steps_exception(self, mock_steps):
        node = obj_utils.create_test_node(self.context)
        mock_steps.side_effect = exception.NodeCleaningFailure('bad')

        with task_manager.acquire(self.context, node.uuid) as task:
            self.assertRaises(exception.NodeCleaningFailure,
                              conductor_steps._validate_user_clean_steps,
                              task, [])
            mock_steps.assert_called_once_with(task, enabled=False, sort=False)

    @mock.patch.object(conductor_steps, '_get_cleaning_steps')
    def test__validate_user_clean_steps_not_supported(self, mock_steps):
        node = obj_utils.create_test_node(self.context)
        mock_steps.return_value = [self.power_update, self.deploy_raid]
        user_steps = [{'step': 'update_firmware', 'interface': 'power'},
                      {'step': 'bad_step', 'interface': 'deploy'}]

        with task_manager.acquire(self.context, node.uuid) as task:
            self.assertRaisesRegex(exception.InvalidParameterValue,
                                   "does not support.*bad_step",
                                   conductor_steps._validate_user_clean_steps,
                                   task, user_steps)
            mock_steps.assert_called_once_with(task, enabled=False, sort=False)

    @mock.patch.object(conductor_steps, '_get_cleaning_steps')
    def test__validate_user_clean_steps_invalid_arg(self, mock_steps):
        node = obj_utils.create_test_node(self.context)
        mock_steps.return_value = self.clean_steps
        user_steps = [{'step': 'update_firmware', 'interface': 'power',
                       'args': {'arg1': 'val1', 'arg2': 'val2'}},
                      {'step': 'erase_disks', 'interface': 'deploy'}]

        with task_manager.acquire(self.context, node.uuid) as task:
            self.assertRaisesRegex(exception.InvalidParameterValue,
                                   "update_firmware.*unexpected.*arg1",
                                   conductor_steps._validate_user_clean_steps,
                                   task, user_steps)
            mock_steps.assert_called_once_with(task, enabled=False, sort=False)

    @mock.patch.object(conductor_steps, '_get_cleaning_steps')
    def test__validate_user_clean_steps_missing_required_arg(self, mock_steps):
        node = obj_utils.create_test_node(self.context)
        mock_steps.return_value = [self.power_update, self.deploy_raid]
        user_steps = [{'step': 'update_firmware', 'interface': 'power'},
                      {'step': 'build_raid', 'interface': 'deploy'}]

        with task_manager.acquire(self.context, node.uuid) as task:
            self.assertRaisesRegex(exception.InvalidParameterValue,
                                   "build_raid.*missing.*arg1",
                                   conductor_steps._validate_user_clean_steps,
                                   task, user_steps)
            mock_steps.assert_called_once_with(task, enabled=False, sort=False)


@mock.patch.object(conductor_steps, '_get_deployment_templates',
                   autospec=True)
@mock.patch.object(conductor_steps, '_get_steps_from_deployment_templates',
                   autospec=True)
@mock.patch.object(conductor_steps, '_validate_user_deploy_steps',
                   autospec=True)
class GetValidatedStepsFromTemplatesTestCase(db_base.DbTestCase):

    def setUp(self):
        super(GetValidatedStepsFromTemplatesTestCase, self).setUp()
        self.node = obj_utils.create_test_node(self.context,
                                               driver='fake-hardware')
        self.template = obj_utils.get_test_deploy_template(self.context)

    def test_ok(self, mock_validate, mock_steps, mock_templates):
        mock_templates.return_value = [self.template]
        steps = [db_utils.get_test_deploy_template_step()]
        mock_steps.return_value = steps
        mock_validate.return_value = steps
        with task_manager.acquire(
                self.context, self.node.uuid, shared=False) as task:
            result = conductor_steps._get_validated_steps_from_templates(task)
            self.assertEqual(steps, result)
            mock_templates.assert_called_once_with(task)
            mock_steps.assert_called_once_with(task, [self.template])
            mock_validate.assert_called_once_with(task, steps, mock.ANY,
                                                  skip_missing=False)

    def test_skip_missing(self, mock_validate, mock_steps, mock_templates):
        mock_templates.return_value = [self.template]
        steps = [db_utils.get_test_deploy_template_step()]
        mock_steps.return_value = steps
        mock_validate.return_value = steps
        with task_manager.acquire(
                self.context, self.node.uuid, shared=False) as task:
            result = conductor_steps._get_validated_steps_from_templates(
                task, skip_missing=True)
            self.assertEqual(steps, result)
            mock_templates.assert_called_once_with(task)
            mock_steps.assert_called_once_with(task, [self.template])
            mock_validate.assert_called_once_with(task, steps, mock.ANY,
                                                  skip_missing=True)

    def test_invalid_parameter_value(self, mock_validate, mock_steps,
                                     mock_templates):
        mock_templates.return_value = [self.template]
        mock_validate.side_effect = exception.InvalidParameterValue('fake')
        with task_manager.acquire(
                self.context, self.node.uuid, shared=False) as task:
            self.assertRaises(
                exception.InvalidParameterValue,
                conductor_steps._get_validated_steps_from_templates, task)

    def test_instance_deploy_failure(self, mock_validate, mock_steps,
                                     mock_templates):
        mock_templates.return_value = [self.template]
        mock_validate.side_effect = exception.InstanceDeployFailure('foo')
        with task_manager.acquire(
                self.context, self.node.uuid, shared=False) as task:
            self.assertRaises(
                exception.InstanceDeployFailure,
                conductor_steps._get_validated_steps_from_templates, task)


@mock.patch.object(conductor_steps, '_get_validated_steps_from_templates',
                   autospec=True)
class ValidateDeployTemplatesTestCase(db_base.DbTestCase):

    def setUp(self):
        super(ValidateDeployTemplatesTestCase, self).setUp()
        self.node = obj_utils.create_test_node(self.context,
                                               driver='fake-hardware')

    def test_ok(self, mock_validated):
        with task_manager.acquire(
                self.context, self.node.uuid, shared=False) as task:
            result = conductor_steps.validate_deploy_templates(task)
            self.assertIsNone(result)
            mock_validated.assert_called_once_with(task, skip_missing=False)

    def test_skip_missing(self, mock_validated):
        with task_manager.acquire(
                self.context, self.node.uuid, shared=False) as task:
            result = conductor_steps.validate_deploy_templates(
                task, skip_missing=True)
            self.assertIsNone(result)
            mock_validated.assert_called_once_with(task, skip_missing=True)

    def test_error(self, mock_validated):
        with task_manager.acquire(
                self.context, self.node.uuid, shared=False) as task:
            mock_validated.side_effect = exception.InvalidParameterValue('foo')
            self.assertRaises(exception.InvalidParameterValue,
                              conductor_steps.validate_deploy_templates, task)
            mock_validated.assert_called_once_with(task, skip_missing=False)
