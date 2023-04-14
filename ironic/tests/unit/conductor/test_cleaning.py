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

"""Tests for cleaning bits."""

from unittest import mock

from oslo_config import cfg
from oslo_utils import uuidutils

from ironic.common import exception
from ironic.common import faults
from ironic.common import states
from ironic.conductor import cleaning
from ironic.conductor import steps as conductor_steps
from ironic.conductor import task_manager
from ironic.conductor import utils as conductor_utils
from ironic.drivers.modules import fake
from ironic.drivers.modules.network import flat as n_flat
from ironic.tests.unit.db import base as db_base
from ironic.tests.unit.objects import utils as obj_utils

CONF = cfg.CONF


class DoNodeCleanTestCase(db_base.DbTestCase):
    def setUp(self):
        super(DoNodeCleanTestCase, self).setUp()
        self.config(automated_clean=True, group='conductor')
        self.power_update = {
            'step': 'update_firmware', 'priority': 10, 'interface': 'power'}
        self.deploy_update = {
            'step': 'update_firmware', 'priority': 10, 'interface': 'deploy'}
        self.deploy_erase = {
            'step': 'erase_disks', 'priority': 20, 'interface': 'deploy'}
        # Automated cleaning should be executed in this order
        self.clean_steps = [self.deploy_erase, self.power_update,
                            self.deploy_update]
        self.next_clean_step_index = 1
        # Manual clean step
        self.deploy_raid = {
            'step': 'build_raid', 'priority': 0, 'interface': 'deploy'}

    def __do_node_clean_validate_fail(self, mock_validate, clean_steps=None):
        tgt_prov_state = states.MANAGEABLE if clean_steps else states.AVAILABLE
        node = obj_utils.create_test_node(
            self.context, driver='fake-hardware',
            provision_state=states.CLEANING,
            target_provision_state=tgt_prov_state)
        with task_manager.acquire(
                self.context, node.uuid, shared=False) as task:
            cleaning.do_node_clean(task, clean_steps=clean_steps)
        node.refresh()
        self.assertEqual(states.CLEANFAIL, node.provision_state)
        self.assertEqual(tgt_prov_state, node.target_provision_state)
        self.assertFalse(node.maintenance)
        self.assertIsNone(node.fault)
        mock_validate.assert_called_once_with(mock.ANY, mock.ANY)

    def __do_node_clean_validate_fail_invalid(self, mock_validate,
                                              clean_steps=None):
        # InvalidParameterValue should cause node to go to CLEANFAIL
        mock_validate.side_effect = exception.InvalidParameterValue('error')
        self.__do_node_clean_validate_fail(mock_validate,
                                           clean_steps=clean_steps)

    @mock.patch('ironic.drivers.modules.fake.FakePower.validate',
                autospec=True)
    def test__do_node_clean_automated_power_validate_fail(self, mock_validate):
        self.__do_node_clean_validate_fail_invalid(mock_validate)

    @mock.patch('ironic.drivers.modules.fake.FakePower.validate',
                autospec=True)
    def test__do_node_clean_manual_power_validate_fail(self, mock_validate):
        self.__do_node_clean_validate_fail_invalid(mock_validate,
                                                   clean_steps=[])

    @mock.patch('ironic.drivers.modules.network.flat.FlatNetwork.validate',
                autospec=True)
    def test__do_node_clean_automated_network_validate_fail(self,
                                                            mock_validate):
        self.__do_node_clean_validate_fail_invalid(mock_validate)

    @mock.patch('ironic.drivers.modules.network.flat.FlatNetwork.validate',
                autospec=True)
    def test__do_node_clean_manual_network_validate_fail(self, mock_validate):
        self.__do_node_clean_validate_fail_invalid(mock_validate,
                                                   clean_steps=[])

    @mock.patch('ironic.drivers.modules.network.flat.FlatNetwork.validate',
                autospec=True)
    def test__do_node_clean_network_error_fail(self, mock_validate):
        # NetworkError should cause node to go to CLEANFAIL
        mock_validate.side_effect = exception.NetworkError()
        self.__do_node_clean_validate_fail(mock_validate)

    @mock.patch.object(conductor_utils, 'LOG', autospec=True)
    @mock.patch.object(conductor_steps, 'set_node_cleaning_steps',
                       autospec=True)
    @mock.patch.object(cleaning, 'do_next_clean_step', autospec=True)
    @mock.patch('ironic.drivers.modules.fake.FakeDeploy.prepare_cleaning',
                autospec=True)
    @mock.patch('ironic.drivers.modules.network.flat.FlatNetwork.validate',
                autospec=True)
    @mock.patch('ironic.drivers.modules.fake.FakeBIOS.cache_bios_settings',
                autospec=True)
    def _test__do_node_clean_cache_bios(self, mock_bios, mock_validate,
                                        mock_prep, mock_next_step, mock_steps,
                                        mock_log, clean_steps=None,
                                        enable_unsupported=False,
                                        enable_exception=False):
        if enable_unsupported:
            mock_bios.side_effect = exception.UnsupportedDriverExtension('')
        elif enable_exception:
            mock_bios.side_effect = exception.IronicException('test')
        mock_prep.return_value = states.NOSTATE
        tgt_prov_state = states.MANAGEABLE if clean_steps else states.AVAILABLE
        node = obj_utils.create_test_node(
            self.context, driver='fake-hardware',
            provision_state=states.CLEANING,
            target_provision_state=tgt_prov_state)
        with task_manager.acquire(
                self.context, node.uuid, shared=False) as task:
            cleaning.do_node_clean(task, clean_steps=clean_steps)
            node.refresh()
            mock_bios.assert_called_once_with(mock.ANY, task)
            if clean_steps:
                self.assertEqual(states.CLEANING, node.provision_state)
                self.assertEqual(tgt_prov_state, node.target_provision_state)
            else:
                self.assertEqual(states.CLEANING, node.provision_state)
                self.assertEqual(states.AVAILABLE, node.target_provision_state)
            mock_validate.assert_called_once_with(mock.ANY, task)
            if enable_exception:
                mock_log.exception.assert_called_once_with(
                    'Caching of bios settings failed on node {}.'
                    .format(node.uuid))

    def test__do_node_clean_manual_cache_bios(self):
        self._test__do_node_clean_cache_bios(clean_steps=[self.deploy_raid])

    def test__do_node_clean_automated_cache_bios(self):
        self._test__do_node_clean_cache_bios()

    def test__do_node_clean_manual_cache_bios_exception(self):
        self._test__do_node_clean_cache_bios(clean_steps=[self.deploy_raid],
                                             enable_exception=True)

    def test__do_node_clean_automated_cache_bios_exception(self):
        self._test__do_node_clean_cache_bios(enable_exception=True)

    def test__do_node_clean_manual_cache_bios_unsupported(self):
        self._test__do_node_clean_cache_bios(clean_steps=[self.deploy_raid],
                                             enable_unsupported=True)

    def test__do_node_clean_automated_cache_bios_unsupported(self):
        self._test__do_node_clean_cache_bios(enable_unsupported=True)

    @mock.patch('ironic.drivers.modules.fake.FakePower.validate',
                autospec=True)
    def test__do_node_clean_automated_disabled(self, mock_validate):
        self.config(automated_clean=False, group='conductor')

        node = obj_utils.create_test_node(
            self.context, driver='fake-hardware',
            provision_state=states.CLEANING,
            target_provision_state=states.AVAILABLE,
            last_error=None)
        with task_manager.acquire(
                self.context, node.uuid, shared=False) as task:
            cleaning.do_node_clean(task)
        node.refresh()

        # Assert that the node was moved to available without cleaning
        self.assertFalse(mock_validate.called)
        self.assertEqual(states.AVAILABLE, node.provision_state)
        self.assertEqual(states.NOSTATE, node.target_provision_state)
        self.assertEqual({}, node.clean_step)
        self.assertNotIn('clean_steps', node.driver_internal_info)
        self.assertNotIn('clean_step_index', node.driver_internal_info)

    @mock.patch('ironic.drivers.modules.fake.FakePower.validate',
                autospec=True)
    @mock.patch('ironic.drivers.modules.network.flat.FlatNetwork.validate',
                autospec=True)
    def test__do_node_clean_automated_disabled_individual_enabled(
            self, mock_network, mock_validate):
        self.config(automated_clean=False, group='conductor')

        node = obj_utils.create_test_node(
            self.context, driver='fake-hardware',
            provision_state=states.CLEANING,
            target_provision_state=states.AVAILABLE,
            last_error=None, automated_clean=True)
        with task_manager.acquire(
                self.context, node.uuid, shared=False) as task:
            cleaning.do_node_clean(task)
        node.refresh()

        # Assert that the node clean was called
        self.assertTrue(mock_validate.called)
        self.assertIn('clean_steps', node.driver_internal_info)

    @mock.patch('ironic.drivers.modules.fake.FakePower.validate',
                autospec=True)
    def test__do_node_clean_automated_enabled_individual_disabled(
            self, mock_validate):
        self.config(automated_clean=True, group='conductor')

        node = obj_utils.create_test_node(
            self.context, driver='fake-hardware',
            provision_state=states.CLEANING,
            target_provision_state=states.AVAILABLE,
            last_error=None, automated_clean=False)
        with task_manager.acquire(
                self.context, node.uuid, shared=False) as task:
            cleaning.do_node_clean(task)
        node.refresh()

        # Assert that the node was moved to available without cleaning
        self.assertFalse(mock_validate.called)
        self.assertEqual(states.AVAILABLE, node.provision_state)
        self.assertEqual(states.NOSTATE, node.target_provision_state)
        self.assertEqual({}, node.clean_step)
        self.assertNotIn('clean_steps', node.driver_internal_info)
        self.assertNotIn('clean_step_index', node.driver_internal_info)

    @mock.patch('ironic.drivers.modules.fake.FakePower.validate',
                autospec=True)
    def test__do_node_clean_automated_disabled_individual_disabled(
            self, mock_validate):
        self.config(automated_clean=False, group='conductor')

        node = obj_utils.create_test_node(
            self.context, driver='fake-hardware',
            provision_state=states.CLEANING,
            target_provision_state=states.AVAILABLE,
            last_error=None, automated_clean=False)
        with task_manager.acquire(
                self.context, node.uuid, shared=False) as task:
            cleaning.do_node_clean(task)
        node.refresh()

        # Assert that the node was moved to available without cleaning
        self.assertFalse(mock_validate.called)
        self.assertEqual(states.AVAILABLE, node.provision_state)
        self.assertEqual(states.NOSTATE, node.target_provision_state)
        self.assertEqual({}, node.clean_step)
        self.assertNotIn('clean_steps', node.driver_internal_info)
        self.assertNotIn('clean_step_index', node.driver_internal_info)

    @mock.patch('ironic.drivers.modules.fake.FakePower.validate',
                autospec=True)
    @mock.patch('ironic.drivers.modules.network.flat.FlatNetwork.validate',
                autospec=True)
    def test__do_node_clean_automated_enabled(self, mock_validate,
                                              mock_network):
        self.config(automated_clean=True, group='conductor')

        node = obj_utils.create_test_node(
            self.context, driver='fake-hardware',
            provision_state=states.CLEANING,
            target_provision_state=states.AVAILABLE,
            last_error=None,
            driver_internal_info={'agent_url': 'url'})
        with task_manager.acquire(
                self.context, node.uuid, shared=False) as task:
            cleaning.do_node_clean(task)
        node.refresh()

        # Assert that the node was cleaned
        self.assertTrue(mock_validate.called)
        self.assertIn('clean_steps', node.driver_internal_info)
        self.assertNotIn('agent_url', node.driver_internal_info)

    @mock.patch('ironic.drivers.modules.fake.FakePower.validate',
                autospec=True)
    @mock.patch('ironic.drivers.modules.network.flat.FlatNetwork.validate',
                autospec=True)
    def test__do_node_clean_automated_enabled_individual_enabled(
            self, mock_network, mock_validate):
        self.config(automated_clean=True, group='conductor')

        node = obj_utils.create_test_node(
            self.context, driver='fake-hardware',
            provision_state=states.CLEANING,
            target_provision_state=states.AVAILABLE,
            last_error=None, automated_clean=True)
        with task_manager.acquire(
                self.context, node.uuid, shared=False) as task:
            cleaning.do_node_clean(task)
        node.refresh()

        # Assert that the node was cleaned
        self.assertTrue(mock_validate.called)
        self.assertIn('clean_steps', node.driver_internal_info)

    @mock.patch('ironic.drivers.modules.fake.FakePower.validate',
                autospec=True)
    @mock.patch('ironic.drivers.modules.network.flat.FlatNetwork.validate',
                autospec=True)
    def test__do_node_clean_automated_enabled_individual_none(
            self, mock_validate, mock_network):
        self.config(automated_clean=True, group='conductor')

        node = obj_utils.create_test_node(
            self.context, driver='fake-hardware',
            provision_state=states.CLEANING,
            target_provision_state=states.AVAILABLE,
            last_error=None, automated_clean=None)
        with task_manager.acquire(
                self.context, node.uuid, shared=False) as task:
            cleaning.do_node_clean(task)
        node.refresh()

        # Assert that the node was cleaned
        self.assertTrue(mock_validate.called)
        self.assertIn('clean_steps', node.driver_internal_info)

    @mock.patch('ironic.drivers.modules.fake.FakeDeploy.tear_down_cleaning',
                autospec=True)
    @mock.patch('ironic.drivers.modules.fake.FakeDeploy.prepare_cleaning',
                autospec=True)
    def test__do_node_clean_maintenance(self, mock_prep, mock_tear_down):
        CONF.set_override('allow_provisioning_in_maintenance', False,
                          group='conductor')
        node = obj_utils.create_test_node(
            self.context, driver='fake-hardware',
            provision_state=states.CLEANING,
            target_provision_state=states.AVAILABLE,
            maintenance=True,
            maintenance_reason='Original reason')
        with task_manager.acquire(
                self.context, node.uuid, shared=False) as task:
            cleaning.do_node_clean(task)
            node.refresh()
            self.assertEqual(states.CLEANFAIL, node.provision_state)
            self.assertEqual(states.AVAILABLE, node.target_provision_state)
            self.assertIn('is not allowed', node.last_error)
            self.assertTrue(node.maintenance)
            self.assertEqual('Original reason', node.maintenance_reason)
            self.assertIsNone(node.fault)  # no clean step running
        self.assertFalse(mock_prep.called)
        self.assertFalse(mock_tear_down.called)

    @mock.patch('ironic.drivers.modules.network.flat.FlatNetwork.validate',
                autospec=True)
    @mock.patch('ironic.drivers.modules.fake.FakeDeploy.prepare_cleaning',
                autospec=True)
    def __do_node_clean_prepare_clean_fail(self, mock_prep, mock_validate,
                                           clean_steps=None):
        # Exception from task.driver.deploy.prepare_cleaning should cause node
        # to go to CLEANFAIL
        mock_prep.side_effect = exception.InvalidParameterValue('error')
        tgt_prov_state = states.MANAGEABLE if clean_steps else states.AVAILABLE
        node = obj_utils.create_test_node(
            self.context, driver='fake-hardware',
            provision_state=states.CLEANING,
            target_provision_state=tgt_prov_state)
        with task_manager.acquire(
                self.context, node.uuid, shared=False) as task:
            cleaning.do_node_clean(task, clean_steps=clean_steps)
            node.refresh()
            self.assertEqual(states.CLEANFAIL, node.provision_state)
            self.assertEqual(tgt_prov_state, node.target_provision_state)
            mock_prep.assert_called_once_with(mock.ANY, task)
            mock_validate.assert_called_once_with(mock.ANY, task)
            self.assertFalse(node.maintenance)
            self.assertIsNone(node.fault)

    def test__do_node_clean_automated_prepare_clean_fail(self):
        self.__do_node_clean_prepare_clean_fail()

    def test__do_node_clean_manual_prepare_clean_fail(self):
        self.__do_node_clean_prepare_clean_fail(clean_steps=[self.deploy_raid])

    @mock.patch('ironic.drivers.modules.network.flat.FlatNetwork.validate',
                autospec=True)
    @mock.patch('ironic.drivers.modules.fake.FakeDeploy.prepare_cleaning',
                autospec=True)
    def __do_node_clean_prepare_clean_wait(self, mock_prep, mock_validate,
                                           clean_steps=None):
        mock_prep.return_value = states.CLEANWAIT
        tgt_prov_state = states.MANAGEABLE if clean_steps else states.AVAILABLE
        node = obj_utils.create_test_node(
            self.context, driver='fake-hardware',
            provision_state=states.CLEANING,
            target_provision_state=tgt_prov_state)
        with task_manager.acquire(
                self.context, node.uuid, shared=False) as task:
            cleaning.do_node_clean(task, clean_steps=clean_steps)
        node.refresh()
        self.assertEqual(states.CLEANWAIT, node.provision_state)
        self.assertEqual(tgt_prov_state, node.target_provision_state)
        mock_prep.assert_called_once_with(mock.ANY, mock.ANY)
        mock_validate.assert_called_once_with(mock.ANY, mock.ANY)

    def test__do_node_clean_automated_prepare_clean_wait(self):
        self.__do_node_clean_prepare_clean_wait()

    def test__do_node_clean_manual_prepare_clean_wait(self):
        self.__do_node_clean_prepare_clean_wait(clean_steps=[self.deploy_raid])

    @mock.patch.object(n_flat.FlatNetwork, 'validate', autospec=True)
    @mock.patch.object(conductor_steps, 'set_node_cleaning_steps',
                       autospec=True)
    def __do_node_clean_steps_fail(self, mock_steps, mock_validate,
                                   clean_steps=None, invalid_exc=True):
        if invalid_exc:
            mock_steps.side_effect = exception.InvalidParameterValue('invalid')
        else:
            mock_steps.side_effect = exception.NodeCleaningFailure('failure')
        tgt_prov_state = states.MANAGEABLE if clean_steps else states.AVAILABLE
        node = obj_utils.create_test_node(
            self.context, driver='fake-hardware',
            uuid=uuidutils.generate_uuid(),
            provision_state=states.CLEANING,
            target_provision_state=tgt_prov_state)
        with task_manager.acquire(
                self.context, node.uuid, shared=False) as task:
            cleaning.do_node_clean(task, clean_steps=clean_steps)
            mock_validate.assert_called_once_with(mock.ANY, task)
        node.refresh()
        self.assertEqual(states.CLEANFAIL, node.provision_state)
        self.assertEqual(tgt_prov_state, node.target_provision_state)
        mock_steps.assert_called_once_with(mock.ANY, disable_ramdisk=False)
        self.assertFalse(node.maintenance)
        self.assertIsNone(node.fault)

    @mock.patch('ironic.drivers.modules.fake.FakePower.set_power_state',
                autospec=True)
    @mock.patch.object(n_flat.FlatNetwork, 'validate', autospec=True)
    @mock.patch.object(conductor_steps, 'set_node_cleaning_steps',
                       autospec=True)
    def test_do_node_clean_steps_fail_poweroff(self, mock_steps, mock_validate,
                                               mock_power, clean_steps=None,
                                               invalid_exc=True):
        if invalid_exc:
            mock_steps.side_effect = exception.InvalidParameterValue('invalid')
        else:
            mock_steps.side_effect = exception.NodeCleaningFailure('failure')
        tgt_prov_state = states.MANAGEABLE if clean_steps else states.AVAILABLE
        self.config(poweroff_in_cleanfail=True, group='conductor')
        node = obj_utils.create_test_node(
            self.context, driver='fake-hardware',
            uuid=uuidutils.generate_uuid(),
            provision_state=states.CLEANING,
            power_state=states.POWER_ON,
            target_provision_state=tgt_prov_state)
        with task_manager.acquire(
                self.context, node.uuid, shared=False) as task:
            cleaning.do_node_clean(task, clean_steps=clean_steps)
            mock_validate.assert_called_once_with(mock.ANY, task)
        node.refresh()
        self.assertEqual(states.CLEANFAIL, node.provision_state)
        self.assertEqual(tgt_prov_state, node.target_provision_state)
        mock_steps.assert_called_once_with(mock.ANY, disable_ramdisk=False)
        self.assertTrue(mock_power.called)

    def test__do_node_clean_automated_steps_fail(self):
        for invalid in (True, False):
            self.__do_node_clean_steps_fail(invalid_exc=invalid)

    def test__do_node_clean_manual_steps_fail(self):
        for invalid in (True, False):
            self.__do_node_clean_steps_fail(clean_steps=[self.deploy_raid],
                                            invalid_exc=invalid)

    @mock.patch.object(conductor_steps, 'set_node_cleaning_steps',
                       autospec=True)
    @mock.patch.object(cleaning, 'do_next_clean_step', autospec=True)
    @mock.patch('ironic.drivers.modules.network.flat.FlatNetwork.validate',
                autospec=True)
    @mock.patch('ironic.drivers.modules.fake.FakePower.validate',
                autospec=True)
    def __do_node_clean(self, mock_power_valid, mock_network_valid,
                        mock_next_step, mock_steps, clean_steps=None,
                        disable_ramdisk=False):
        if clean_steps:
            tgt_prov_state = states.MANAGEABLE
        else:
            tgt_prov_state = states.AVAILABLE

            def set_steps(task, disable_ramdisk=None):
                dii = task.node.driver_internal_info
                dii['clean_steps'] = self.clean_steps
                task.node.driver_internal_info = dii
                task.node.save()

            mock_steps.side_effect = set_steps

        node = obj_utils.create_test_node(
            self.context, driver='fake-hardware',
            provision_state=states.CLEANING,
            target_provision_state=tgt_prov_state,
            last_error=None,
            power_state=states.POWER_OFF,
            driver_internal_info={'agent_secret_token': 'old'})

        with task_manager.acquire(
                self.context, node.uuid, shared=False) as task:
            cleaning.do_node_clean(task, clean_steps=clean_steps,
                                   disable_ramdisk=disable_ramdisk)

            node.refresh()

            mock_power_valid.assert_called_once_with(mock.ANY, task)
            if disable_ramdisk:
                mock_network_valid.assert_not_called()
            else:
                mock_network_valid.assert_called_once_with(mock.ANY, task)

            mock_next_step.assert_called_once_with(
                task, 0, disable_ramdisk=disable_ramdisk)
            mock_steps.assert_called_once_with(
                task, disable_ramdisk=disable_ramdisk)
            if clean_steps:
                self.assertEqual(clean_steps,
                                 node.driver_internal_info['clean_steps'])
            self.assertFalse(node.maintenance)
            self.assertNotIn('agent_secret_token', node.driver_internal_info)

        # Check that state didn't change
        self.assertEqual(states.CLEANING, node.provision_state)
        self.assertEqual(tgt_prov_state, node.target_provision_state)

    def test__do_node_clean_automated(self):
        self.__do_node_clean()

    def test__do_node_clean_manual(self):
        self.__do_node_clean(clean_steps=[self.deploy_raid])

    def test__do_node_clean_manual_disable_ramdisk(self):
        self.__do_node_clean(clean_steps=[self.deploy_raid],
                             disable_ramdisk=True)

    @mock.patch('ironic.drivers.modules.fake.FakeDeploy.execute_clean_step',
                autospec=True)
    def _do_next_clean_step_first_step_async(self, return_state, mock_execute,
                                             clean_steps=None):
        # Execute the first async clean step on a node
        driver_internal_info = {'clean_step_index': None}
        if clean_steps:
            tgt_prov_state = states.MANAGEABLE
            driver_internal_info['clean_steps'] = clean_steps
        else:
            tgt_prov_state = states.AVAILABLE
            driver_internal_info['clean_steps'] = self.clean_steps

        node = obj_utils.create_test_node(
            self.context, driver='fake-hardware',
            provision_state=states.CLEANING,
            target_provision_state=tgt_prov_state,
            last_error=None,
            driver_internal_info=driver_internal_info,
            clean_step={})
        mock_execute.return_value = return_state
        expected_first_step = node.driver_internal_info['clean_steps'][0]

        with task_manager.acquire(
                self.context, node.uuid, shared=False) as task:
            cleaning.do_next_clean_step(task, 0)

        node.refresh()

        self.assertEqual(states.CLEANWAIT, node.provision_state)
        self.assertEqual(tgt_prov_state, node.target_provision_state)
        self.assertEqual(expected_first_step, node.clean_step)
        self.assertEqual(0, node.driver_internal_info['clean_step_index'])
        mock_execute.assert_called_once_with(
            mock.ANY, mock.ANY, expected_first_step)

    def test_do_next_clean_step_automated_first_step_async(self):
        self._do_next_clean_step_first_step_async(states.CLEANWAIT)

    def test_do_next_clean_step_manual_first_step_async(self):
        self._do_next_clean_step_first_step_async(
            states.CLEANWAIT, clean_steps=[self.deploy_raid])

    @mock.patch('ironic.drivers.modules.fake.FakePower.execute_clean_step',
                autospec=True)
    def _do_next_clean_step_continue_from_last_cleaning(self, return_state,
                                                        mock_execute,
                                                        manual=False):
        # Resume an in-progress cleaning after the first async step
        tgt_prov_state = states.MANAGEABLE if manual else states.AVAILABLE

        node = obj_utils.create_test_node(
            self.context, driver='fake-hardware',
            provision_state=states.CLEANING,
            target_provision_state=tgt_prov_state,
            last_error=None,
            driver_internal_info={'clean_steps': self.clean_steps,
                                  'clean_step_index': 0},
            clean_step=self.clean_steps[0])
        mock_execute.return_value = return_state

        with task_manager.acquire(
                self.context, node.uuid, shared=False) as task:
            cleaning.do_next_clean_step(task, self.next_clean_step_index)

        node.refresh()

        self.assertEqual(states.CLEANWAIT, node.provision_state)
        self.assertEqual(tgt_prov_state, node.target_provision_state)
        self.assertEqual(self.clean_steps[1], node.clean_step)
        self.assertEqual(1, node.driver_internal_info['clean_step_index'])
        mock_execute.assert_called_once_with(
            mock.ANY, mock.ANY, self.clean_steps[1])

    def test_do_next_clean_step_continue_from_last_cleaning(self):
        self._do_next_clean_step_continue_from_last_cleaning(states.CLEANWAIT)

    def test_do_next_clean_step_manual_continue_from_last_cleaning(self):
        self._do_next_clean_step_continue_from_last_cleaning(states.CLEANWAIT,
                                                             manual=True)

    @mock.patch('ironic.drivers.modules.fake.FakeDeploy.execute_clean_step',
                autospec=True)
    def _do_next_clean_step_last_step_noop(self, mock_execute, manual=False,
                                           retired=False, fast_track=False):
        if fast_track:
            self.config(fast_track=True, group='deploy')
        # Resume where last_step is the last cleaning step, should be noop
        tgt_prov_state = states.MANAGEABLE if manual else states.AVAILABLE
        info = {'clean_steps': self.clean_steps,
                'clean_step_index': len(self.clean_steps) - 1,
                'agent_url': 'test-url',
                'agent_secret_token': 'token'}

        node = obj_utils.create_test_node(
            self.context, driver='fake-hardware',
            provision_state=states.CLEANING,
            target_provision_state=tgt_prov_state,
            last_error=None,
            driver_internal_info=info,
            clean_step=self.clean_steps[-1],
            retired=retired)

        with task_manager.acquire(
                self.context, node.uuid, shared=False) as task:
            cleaning.do_next_clean_step(task, None)

        node.refresh()

        # retired nodes move to manageable upon cleaning
        if retired:
            tgt_prov_state = states.MANAGEABLE

        # Cleaning should be complete without calling additional steps
        self.assertEqual(tgt_prov_state, node.provision_state)
        self.assertEqual(states.NOSTATE, node.target_provision_state)
        self.assertEqual({}, node.clean_step)
        self.assertNotIn('clean_step_index', node.driver_internal_info)
        self.assertIsNone(node.driver_internal_info['clean_steps'])
        self.assertFalse(mock_execute.called)
        if fast_track:
            self.assertEqual('test-url',
                             node.driver_internal_info.get('agent_url'))
            self.assertIsNotNone(
                node.driver_internal_info.get('agent_secret_token'))
        else:
            self.assertNotIn('agent_url', node.driver_internal_info)
            self.assertNotIn('agent_secret_token',
                             node.driver_internal_info)

    def test__do_next_clean_step_automated_last_step_noop(self):
        self._do_next_clean_step_last_step_noop()

    def test__do_next_clean_step_manual_last_step_noop(self):
        self._do_next_clean_step_last_step_noop(manual=True)

    def test__do_next_clean_step_retired_last_step_change_tgt_state(self):
        self._do_next_clean_step_last_step_noop(retired=True)

    def test__do_next_clean_step_last_step_noop_fast_track(self):
        self._do_next_clean_step_last_step_noop(fast_track=True)

    @mock.patch('ironic.drivers.utils.collect_ramdisk_logs', autospec=True)
    @mock.patch('ironic.drivers.modules.fake.FakeDeploy.tear_down_cleaning',
                autospec=True)
    @mock.patch('ironic.drivers.modules.fake.FakePower.execute_clean_step',
                autospec=True)
    @mock.patch('ironic.drivers.modules.fake.FakeDeploy.execute_clean_step',
                autospec=True)
    def _do_next_clean_step_all(self, mock_deploy_execute,
                                mock_power_execute, mock_tear_down,
                                mock_collect_logs,
                                manual=False, disable_ramdisk=False):
        # Run all steps from start to finish (all synchronous)
        tgt_prov_state = states.MANAGEABLE if manual else states.AVAILABLE

        node = obj_utils.create_test_node(
            self.context, driver='fake-hardware',
            provision_state=states.CLEANING,
            target_provision_state=tgt_prov_state,
            last_error=None,
            driver_internal_info={'clean_steps': self.clean_steps,
                                  'clean_step_index': None},
            clean_step={})

        def fake_deploy(conductor_obj, task, step):
            driver_internal_info = task.node.driver_internal_info
            driver_internal_info['goober'] = 'test'
            task.node.driver_internal_info = driver_internal_info
            task.node.save()

        mock_deploy_execute.side_effect = fake_deploy
        mock_power_execute.return_value = None

        with task_manager.acquire(
                self.context, node.uuid, shared=False) as task:
            cleaning.do_next_clean_step(
                task, 0, disable_ramdisk=disable_ramdisk)

            mock_power_execute.assert_called_once_with(task.driver.power, task,
                                                       self.clean_steps[1])
            mock_deploy_execute.assert_has_calls(
                [mock.call(task.driver.deploy, task, self.clean_steps[0]),
                 mock.call(task.driver.deploy, task, self.clean_steps[2])])
            if disable_ramdisk:
                mock_tear_down.assert_not_called()
            else:
                mock_tear_down.assert_called_once_with(
                    task.driver.deploy, task)

        node.refresh()

        # Cleaning should be complete
        self.assertEqual(tgt_prov_state, node.provision_state)
        self.assertEqual(states.NOSTATE, node.target_provision_state)
        self.assertEqual({}, node.clean_step)
        self.assertNotIn('clean_step_index', node.driver_internal_info)
        self.assertEqual('test', node.driver_internal_info['goober'])
        self.assertIsNone(node.driver_internal_info['clean_steps'])
        self.assertFalse(mock_collect_logs.called)

    def test_do_next_clean_step_automated_all(self):
        self._do_next_clean_step_all()

    def test_do_next_clean_step_manual_all(self):
        self._do_next_clean_step_all(manual=True)

    def test_do_next_clean_step_manual_all_disable_ramdisk(self):
        self._do_next_clean_step_all(manual=True, disable_ramdisk=True)

    @mock.patch('ironic.drivers.utils.collect_ramdisk_logs', autospec=True)
    @mock.patch('ironic.drivers.modules.fake.FakePower.execute_clean_step',
                autospec=True)
    @mock.patch('ironic.drivers.modules.fake.FakeDeploy.execute_clean_step',
                autospec=True)
    def test_do_next_clean_step_collect_logs(self, mock_deploy_execute,
                                             mock_power_execute,
                                             mock_collect_logs):
        CONF.set_override('deploy_logs_collect', 'always', group='agent')
        # Run all steps from start to finish (all synchronous)
        tgt_prov_state = states.MANAGEABLE

        node = obj_utils.create_test_node(
            self.context, driver='fake-hardware',
            provision_state=states.CLEANING,
            target_provision_state=tgt_prov_state,
            last_error=None,
            driver_internal_info={'clean_steps': self.clean_steps,
                                  'clean_step_index': None},
            clean_step={})

        def fake_deploy(conductor_obj, task, step):
            driver_internal_info = task.node.driver_internal_info
            driver_internal_info['goober'] = 'test'
            task.node.driver_internal_info = driver_internal_info
            task.node.save()

        mock_deploy_execute.side_effect = fake_deploy
        mock_power_execute.return_value = None

        with task_manager.acquire(
                self.context, node.uuid, shared=False) as task:
            cleaning.do_next_clean_step(task, 0)

        node.refresh()

        # Cleaning should be complete
        self.assertEqual(tgt_prov_state, node.provision_state)
        self.assertEqual(states.NOSTATE, node.target_provision_state)
        self.assertEqual({}, node.clean_step)
        self.assertNotIn('clean_step_index', node.driver_internal_info)
        self.assertEqual('test', node.driver_internal_info['goober'])
        self.assertIsNone(node.driver_internal_info['clean_steps'])
        mock_power_execute.assert_called_once_with(mock.ANY, mock.ANY,
                                                   self.clean_steps[1])
        mock_deploy_execute.assert_has_calls(
            [mock.call(mock.ANY, mock.ANY, self.clean_steps[0]),
             mock.call(mock.ANY, mock.ANY, self.clean_steps[2])])
        mock_collect_logs.assert_called_once_with(mock.ANY, label='cleaning')

    @mock.patch('ironic.drivers.utils.collect_ramdisk_logs', autospec=True)
    @mock.patch('ironic.drivers.modules.fake.FakeDeploy.execute_clean_step',
                autospec=True)
    @mock.patch.object(fake.FakeDeploy, 'tear_down_cleaning', autospec=True)
    def _do_next_clean_step_execute_fail(self, tear_mock, mock_execute,
                                         mock_collect_logs, manual=False):
        # When a clean step fails, go to CLEANFAIL
        tgt_prov_state = states.MANAGEABLE if manual else states.AVAILABLE

        node = obj_utils.create_test_node(
            self.context, driver='fake-hardware',
            provision_state=states.CLEANING,
            target_provision_state=tgt_prov_state,
            last_error=None,
            driver_internal_info={'clean_steps': self.clean_steps,
                                  'clean_step_index': None},
            clean_step={})
        mock_execute.side_effect = Exception()

        with task_manager.acquire(
                self.context, node.uuid, shared=False) as task:
            cleaning.do_next_clean_step(task, 0)
            tear_mock.assert_called_once_with(task.driver.deploy, task)

        node.refresh()

        # Make sure we go to CLEANFAIL, clear clean_steps
        self.assertEqual(states.CLEANFAIL, node.provision_state)
        self.assertEqual(tgt_prov_state, node.target_provision_state)
        self.assertEqual({}, node.clean_step)
        self.assertNotIn('clean_step_index', node.driver_internal_info)
        self.assertIsNotNone(node.last_error)
        self.assertTrue(node.maintenance)
        self.assertEqual(faults.CLEAN_FAILURE, node.fault)
        mock_execute.assert_called_once_with(
            mock.ANY, mock.ANY, self.clean_steps[0])
        mock_collect_logs.assert_called_once_with(mock.ANY, label='cleaning')

    def test__do_next_clean_step_automated_execute_fail(self):
        self._do_next_clean_step_execute_fail()

    def test__do_next_clean_step_manual_execute_fail(self):
        self._do_next_clean_step_execute_fail(manual=True)

    @mock.patch('ironic.drivers.modules.fake.FakeDeploy.execute_clean_step',
                autospec=True)
    def test_do_next_clean_step_oob_reboot(self, mock_execute):
        # When a clean step fails, go to CLEANWAIT
        tgt_prov_state = states.MANAGEABLE

        node = obj_utils.create_test_node(
            self.context, driver='fake-hardware',
            provision_state=states.CLEANING,
            target_provision_state=tgt_prov_state,
            last_error=None,
            driver_internal_info={'clean_steps': self.clean_steps,
                                  'clean_step_index': None,
                                  'cleaning_reboot': True},
            clean_step={})
        mock_execute.side_effect = exception.AgentConnectionFailed(
            reason='failed')

        with task_manager.acquire(
                self.context, node.uuid, shared=False) as task:
            cleaning.do_next_clean_step(task, 0)

        node.refresh()

        # Make sure we go to CLEANWAIT
        self.assertEqual(states.CLEANWAIT, node.provision_state)
        self.assertEqual(tgt_prov_state, node.target_provision_state)
        self.assertEqual(self.clean_steps[0], node.clean_step)
        self.assertEqual(0, node.driver_internal_info['clean_step_index'])
        self.assertFalse(node.driver_internal_info['skip_current_clean_step'])
        mock_execute.assert_called_once_with(
            mock.ANY, mock.ANY, self.clean_steps[0])

    @mock.patch('ironic.drivers.modules.fake.FakeDeploy.execute_clean_step',
                autospec=True)
    def test_do_next_clean_step_agent_busy(self, mock_execute):
        # When a clean step fails, go to CLEANWAIT
        tgt_prov_state = states.MANAGEABLE

        node = obj_utils.create_test_node(
            self.context, driver='fake-hardware',
            provision_state=states.CLEANING,
            target_provision_state=tgt_prov_state,
            last_error=None,
            driver_internal_info={'clean_steps': self.clean_steps,
                                  'clean_step_index': None,
                                  'cleaning_reboot': True},
            clean_step={})
        mock_execute.side_effect = exception.AgentInProgress(
            reason='still meowing')
        with task_manager.acquire(
                self.context, node.uuid, shared=False) as task:
            cleaning.do_next_clean_step(task, 0)

        node.refresh()
        # Make sure we go to CLEANWAIT
        self.assertEqual(states.CLEANWAIT, node.provision_state)
        self.assertEqual(tgt_prov_state, node.target_provision_state)
        self.assertEqual(self.clean_steps[0], node.clean_step)
        self.assertEqual(0, node.driver_internal_info['clean_step_index'])
        self.assertFalse(node.driver_internal_info['skip_current_clean_step'])
        mock_execute.assert_called_once_with(
            mock.ANY, mock.ANY, self.clean_steps[0])

    @mock.patch('ironic.drivers.modules.fake.FakeDeploy.execute_clean_step',
                autospec=True)
    def test_do_next_clean_step_oob_reboot_last_step(self, mock_execute):
        # Resume where last_step is the last cleaning step
        tgt_prov_state = states.MANAGEABLE
        info = {'clean_steps': self.clean_steps,
                'cleaning_reboot': True,
                'clean_step_index': len(self.clean_steps) - 1}

        node = obj_utils.create_test_node(
            self.context, driver='fake-hardware',
            provision_state=states.CLEANING,
            target_provision_state=tgt_prov_state,
            last_error=None,
            driver_internal_info=info,
            clean_step=self.clean_steps[-1])

        with task_manager.acquire(
                self.context, node.uuid, shared=False) as task:
            cleaning.do_next_clean_step(task, None)

        node.refresh()

        # Cleaning should be complete without calling additional steps
        self.assertEqual(tgt_prov_state, node.provision_state)
        self.assertEqual(states.NOSTATE, node.target_provision_state)
        self.assertEqual({}, node.clean_step)
        self.assertNotIn('clean_step_index', node.driver_internal_info)
        self.assertNotIn('cleaning_reboot', node.driver_internal_info)
        self.assertIsNone(node.driver_internal_info['clean_steps'])
        self.assertFalse(mock_execute.called)

    @mock.patch('ironic.drivers.modules.fake.FakeDeploy.execute_clean_step',
                autospec=True)
    @mock.patch.object(fake.FakeDeploy, 'tear_down_cleaning', autospec=True)
    def test_do_next_clean_step_oob_reboot_fail(self, tear_mock,
                                                mock_execute):
        # When a clean step fails with no reboot requested go to CLEANFAIL
        tgt_prov_state = states.MANAGEABLE

        node = obj_utils.create_test_node(
            self.context, driver='fake-hardware',
            provision_state=states.CLEANING,
            target_provision_state=tgt_prov_state,
            last_error=None,
            driver_internal_info={'clean_steps': self.clean_steps,
                                  'clean_step_index': None},
            clean_step={})
        mock_execute.side_effect = exception.AgentConnectionFailed(
            reason='failed')

        with task_manager.acquire(
                self.context, node.uuid, shared=False) as task:
            cleaning.do_next_clean_step(task, 0)
            tear_mock.assert_called_once_with(task.driver.deploy, task)

        node.refresh()

        # Make sure we go to CLEANFAIL, clear clean_steps
        self.assertEqual(states.CLEANFAIL, node.provision_state)
        self.assertEqual(tgt_prov_state, node.target_provision_state)
        self.assertEqual({}, node.clean_step)
        self.assertNotIn('clean_step_index', node.driver_internal_info)
        self.assertNotIn('skip_current_clean_step', node.driver_internal_info)
        self.assertIsNotNone(node.last_error)
        self.assertTrue(node.maintenance)
        mock_execute.assert_called_once_with(
            mock.ANY, mock.ANY, self.clean_steps[0])

    @mock.patch.object(conductor_utils, 'LOG', autospec=True)
    @mock.patch('ironic.drivers.modules.fake.FakeDeploy.execute_clean_step',
                autospec=True)
    @mock.patch('ironic.drivers.modules.fake.FakePower.execute_clean_step',
                autospec=True)
    @mock.patch.object(fake.FakeDeploy, 'tear_down_cleaning', autospec=True)
    def _do_next_clean_step_fail_in_tear_down_cleaning(
            self, tear_mock, power_exec_mock, deploy_exec_mock, log_mock,
            manual=True):
        tgt_prov_state = states.MANAGEABLE if manual else states.AVAILABLE

        node = obj_utils.create_test_node(
            self.context, driver='fake-hardware',
            provision_state=states.CLEANING,
            target_provision_state=tgt_prov_state,
            last_error=None,
            driver_internal_info={'clean_steps': self.clean_steps,
                                  'clean_step_index': None},
            clean_step={})

        deploy_exec_mock.return_value = None
        power_exec_mock.return_value = None
        tear_mock.side_effect = Exception('boom')

        with task_manager.acquire(
                self.context, node.uuid, shared=False) as task:
            cleaning.do_next_clean_step(task, 0)

        node.refresh()

        # Make sure we go to CLEANFAIL, clear clean_steps
        self.assertEqual(states.CLEANFAIL, node.provision_state)
        self.assertEqual(tgt_prov_state, node.target_provision_state)
        self.assertEqual({}, node.clean_step)
        self.assertNotIn('clean_step_index', node.driver_internal_info)
        self.assertIsNotNone(node.last_error)
        self.assertEqual(1, tear_mock.call_count)
        self.assertFalse(node.maintenance)  # no step is running
        deploy_exec_calls = [
            mock.call(mock.ANY, mock.ANY, self.clean_steps[0]),
            mock.call(mock.ANY, mock.ANY, self.clean_steps[2]),
        ]
        self.assertEqual(deploy_exec_calls, deploy_exec_mock.call_args_list)

        power_exec_calls = [
            mock.call(mock.ANY, mock.ANY, self.clean_steps[1]),
        ]
        self.assertEqual(power_exec_calls, power_exec_mock.call_args_list)
        log_mock.error.assert_called_once_with(
            'Failed to tear down from cleaning for node {}, reason: boom'
            .format(node.uuid), exc_info=True)

    def test__do_next_clean_step_automated_fail_in_tear_down_cleaning(self):
        self._do_next_clean_step_fail_in_tear_down_cleaning()

    def test__do_next_clean_step_manual_fail_in_tear_down_cleaning(self):
        self._do_next_clean_step_fail_in_tear_down_cleaning(manual=True)

    @mock.patch('ironic.drivers.modules.fake.FakeDeploy.execute_clean_step',
                autospec=True)
    def _do_next_clean_step_no_steps(self, mock_execute, manual=False,
                                     fast_track=False):
        if fast_track:
            self.config(fast_track=True, group='deploy')

        for info in ({'clean_steps': None, 'clean_step_index': None,
                      'agent_url': 'test-url', 'agent_secret_token': 'magic'},
                     {'clean_steps': None, 'agent_url': 'test-url',
                      'agent_secret_token': 'it_is_a_kind_of_magic'}):
            # Resume where there are no steps, should be a noop
            tgt_prov_state = states.MANAGEABLE if manual else states.AVAILABLE

            node = obj_utils.create_test_node(
                self.context, driver='fake-hardware',
                uuid=uuidutils.generate_uuid(),
                provision_state=states.CLEANING,
                target_provision_state=tgt_prov_state,
                last_error=None,
                driver_internal_info=info,
                clean_step={})

            with task_manager.acquire(
                    self.context, node.uuid, shared=False) as task:
                cleaning.do_next_clean_step(task, None)

            node.refresh()

            # Cleaning should be complete without calling additional steps
            self.assertEqual(tgt_prov_state, node.provision_state)
            self.assertEqual(states.NOSTATE, node.target_provision_state)
            self.assertEqual({}, node.clean_step)
            self.assertNotIn('clean_step_index', node.driver_internal_info)
            self.assertFalse(mock_execute.called)
            if fast_track:
                self.assertEqual('test-url',
                                 node.driver_internal_info.get('agent_url'))
                self.assertIsNotNone(
                    node.driver_internal_info.get('agent_secret_token'))
            else:
                self.assertNotIn('agent_url', node.driver_internal_info)
                self.assertNotIn('agent_secret_token',
                                 node.driver_internal_info)
            mock_execute.reset_mock()

    def test__do_next_clean_step_automated_no_steps(self):
        self._do_next_clean_step_no_steps()

    def test__do_next_clean_step_manual_no_steps(self):
        self._do_next_clean_step_no_steps(manual=True)

    def test__do_next_clean_step_fast_track(self):
        self._do_next_clean_step_no_steps(fast_track=True)

    @mock.patch('ironic.drivers.modules.fake.FakePower.execute_clean_step',
                autospec=True)
    @mock.patch('ironic.drivers.modules.fake.FakeDeploy.execute_clean_step',
                autospec=True)
    def _do_next_clean_step_bad_step_return_value(
            self, deploy_exec_mock, power_exec_mock, manual=False):
        # When a clean step fails, go to CLEANFAIL
        tgt_prov_state = states.MANAGEABLE if manual else states.AVAILABLE

        node = obj_utils.create_test_node(
            self.context, driver='fake-hardware',
            provision_state=states.CLEANING,
            target_provision_state=tgt_prov_state,
            last_error=None,
            driver_internal_info={'clean_steps': self.clean_steps,
                                  'clean_step_index': None},
            clean_step={})
        deploy_exec_mock.return_value = "foo"

        with task_manager.acquire(
                self.context, node.uuid, shared=False) as task:
            cleaning.do_next_clean_step(task, 0)

        node.refresh()

        # Make sure we go to CLEANFAIL, clear clean_steps
        self.assertEqual(states.CLEANFAIL, node.provision_state)
        self.assertEqual(tgt_prov_state, node.target_provision_state)
        self.assertEqual({}, node.clean_step)
        self.assertNotIn('clean_step_index', node.driver_internal_info)
        self.assertIsNotNone(node.last_error)
        self.assertTrue(node.maintenance)  # the 1st clean step was running
        deploy_exec_mock.assert_called_once_with(mock.ANY, mock.ANY,
                                                 self.clean_steps[0])
        # Make sure we don't execute any other step and return
        self.assertFalse(power_exec_mock.called)

    def test__do_next_clean_step_automated_bad_step_return_value(self):
        self._do_next_clean_step_bad_step_return_value()

    def test__do_next_clean_step_manual_bad_step_return_value(self):
        self._do_next_clean_step_bad_step_return_value(manual=True)

    @mock.patch.object(cleaning, 'do_next_clean_step', autospec=True)
    def _continue_node_clean(self, mock_next_step, skip=True):
        # test that skipping current step mechanism works
        driver_info = {'clean_steps': self.clean_steps,
                       'clean_step_index': 0,
                       'cleaning_polling': 'value'}
        if not skip:
            driver_info['skip_current_clean_step'] = skip
        node = obj_utils.create_test_node(
            self.context, driver='fake-hardware',
            provision_state=states.CLEANING,
            target_provision_state=states.MANAGEABLE,
            driver_internal_info=driver_info,
            clean_step=self.clean_steps[0])
        with task_manager.acquire(self.context, node.uuid) as task:
            cleaning.continue_node_clean(task)
            expected_step_index = 1 if skip else 0
            self.assertNotIn(
                'skip_current_clean_step', task.node.driver_internal_info)
            self.assertNotIn(
                'cleaning_polling', task.node.driver_internal_info)
            mock_next_step.assert_called_once_with(task, expected_step_index)

    def test_continue_node_clean(self):
        self._continue_node_clean(skip=True)

    def test_continue_node_clean_no_skip_step(self):
        self._continue_node_clean(skip=False)


class DoNodeCleanAbortTestCase(db_base.DbTestCase):
    @mock.patch.object(fake.FakeDeploy, 'tear_down_cleaning', autospec=True)
    def _test_do_node_clean_abort(self, clean_step, tear_mock):
        node = obj_utils.create_test_node(
            self.context, driver='fake-hardware',
            provision_state=states.CLEANWAIT,
            target_provision_state=states.AVAILABLE,
            clean_step=clean_step,
            driver_internal_info={
                'agent_url': 'some url',
                'agent_secret_token': 'token',
                'clean_step_index': 2,
                'cleaning_reboot': True,
                'cleaning_polling': True,
                'skip_current_clean_step': True})

        with task_manager.acquire(self.context, node.uuid) as task:
            cleaning.do_node_clean_abort(task)
            self.assertIsNotNone(task.node.last_error)
            tear_mock.assert_called_once_with(task.driver.deploy, task)
            if clean_step:
                self.assertIn(clean_step['step'], task.node.last_error)
            # assert node's clean_step and metadata was cleaned up
            self.assertEqual({}, task.node.clean_step)
            self.assertNotIn('clean_step_index',
                             task.node.driver_internal_info)
            self.assertNotIn('cleaning_reboot',
                             task.node.driver_internal_info)
            self.assertNotIn('cleaning_polling',
                             task.node.driver_internal_info)
            self.assertNotIn('skip_current_clean_step',
                             task.node.driver_internal_info)
            self.assertNotIn('agent_url',
                             task.node.driver_internal_info)
            self.assertNotIn('agent_secret_token',
                             task.node.driver_internal_info)

    def test_do_node_clean_abort_early(self):
        self._test_do_node_clean_abort(None)

    def test_do_node_clean_abort_with_step(self):
        self._test_do_node_clean_abort({'step': 'foo', 'interface': 'deploy',
                                        'abortable': True})

    @mock.patch.object(fake.FakeDeploy, 'tear_down_cleaning', autospec=True)
    def test__do_node_clean_abort_tear_down_fail(self, tear_mock):
        tear_mock.side_effect = Exception('Surprise')

        node = obj_utils.create_test_node(
            self.context, driver='fake-hardware',
            provision_state=states.CLEANFAIL,
            target_provision_state=states.AVAILABLE,
            clean_step={'step': 'foo', 'abortable': True})

        with task_manager.acquire(self.context, node.uuid) as task:
            cleaning.do_node_clean_abort(task)
            tear_mock.assert_called_once_with(task.driver.deploy, task)
            self.assertIsNotNone(task.node.last_error)
            self.assertIsNotNone(task.node.maintenance_reason)
            self.assertTrue(task.node.maintenance)
            self.assertEqual('clean failure', task.node.fault)


class DoNodeCleanTestChildNodes(db_base.DbTestCase):
    def setUp(self):
        super(DoNodeCleanTestChildNodes, self).setUp()
        self.config(automated_clean=True, group='conductor')
        self.power_off_parent = {
            'step': 'power_off', 'priority': 4, 'interface': 'power'}
        self.power_on_children = {
            'step': 'power_on', 'priority': 5, 'interface': 'power',
            'execute_on_child_nodes': True}
        self.update_firmware_on_children = {
            'step': 'update_firmware', 'priority': 10,
            'interface': 'management', 'execute_on_child_nodes': True}
        self.reboot_children = {
            'step': 'reboot', 'priority': 5, 'interface': 'power',
            'execute_on_child_nodes': True}
        self.power_on_parent = {
            'step': 'power_on', 'priority': 15, 'interface': 'power'}
        self.clean_steps = [
            self.power_off_parent,
            self.power_on_children,
            self.update_firmware_on_children,
            self.reboot_children,
            self.power_on_parent]
        self.node = obj_utils.create_test_node(
            self.context, driver='fake-hardware',
            provision_state=states.CLEANING,
            target_provision_state=states.MANAGEABLE,
            last_error=None,
            power_state=states.POWER_ON,
            driver_internal_info={'agent_secret_token': 'old',
                                  'clean_steps': self.clean_steps})

    @mock.patch('ironic.drivers.modules.fake.FakePower.reboot',
                autospec=True)
    @mock.patch('ironic.drivers.modules.fake.FakePower.set_power_state',
                autospec=True)
    @mock.patch('ironic.drivers.modules.network.flat.FlatNetwork.validate',
                autospec=True)
    @mock.patch('ironic.drivers.modules.fake.FakePower.validate',
                autospec=True)
    @mock.patch('ironic.drivers.modules.fake.FakePower.execute_clean_step',
                autospec=True)
    @mock.patch('ironic.drivers.modules.fake.FakeManagement.'
                'execute_clean_step', autospec=True)
    @mock.patch('ironic.drivers.modules.fake.FakeDeploy.execute_clean_step',
                autospec=True)
    def test_do_next_clean_step_with_children(
            self, mock_deploy, mock_mgmt, mock_power, mock_pv, mock_nv,
            mock_sps, mock_reboot):
        child_node1 = obj_utils.create_test_node(
            self.context,
            uuid=uuidutils.generate_uuid(),
            driver='fake-hardware',
            last_error=None,
            power_state=states.POWER_OFF,
            parent_node=self.node.uuid)
        child_node2 = obj_utils.create_test_node(
            self.context,
            uuid=uuidutils.generate_uuid(),
            driver='fake-hardware',
            last_error=None,
            power_state=states.POWER_OFF,
            parent_node=self.node.uuid)

        mock_deploy.return_value = None
        mock_mgmt.return_value = None
        mock_power.return_value = None
        child1_updated_at = str(child_node1.updated_at)
        child2_updated_at = str(child_node2.updated_at)
        with task_manager.acquire(
                self.context, self.node.uuid, shared=False) as task:

            cleaning.do_next_clean_step(task, 0,
                                        disable_ramdisk=True)
        self.node.refresh()
        child_node1.refresh()
        child_node2.refresh()

        # Confirm the objects *did* recieve locks.
        self.assertNotEqual(child1_updated_at, child_node1.updated_at)
        self.assertNotEqual(child2_updated_at, child_node2.updated_at)

        # Confirm the child nodes have no errors
        self.assertFalse(child_node1.maintenance)
        self.assertFalse(child_node2.maintenance)
        self.assertIsNone(child_node1.last_error)
        self.assertIsNone(child_node2.last_error)
        self.assertIsNone(self.node.last_error)

        # Confirm the call counts expected
        self.assertEqual(0, mock_deploy.call_count)
        self.assertEqual(2, mock_mgmt.call_count)
        self.assertEqual(0, mock_power.call_count)
        self.assertEqual(0, mock_nv.call_count)
        self.assertEqual(0, mock_pv.call_count)
        self.assertEqual(4, mock_sps.call_count)
        self.assertEqual(2, mock_reboot.call_count)
        mock_sps.assert_has_calls([
            mock.call(mock.ANY, mock.ANY, 'power off', timeout=None),
            mock.call(mock.ANY, mock.ANY, 'power on', timeout=None),
            mock.call(mock.ANY, mock.ANY, 'power on', timeout=None)])

    @mock.patch('ironic.drivers.modules.fake.FakePower.set_power_state',
                autospec=True)
    @mock.patch('ironic.drivers.modules.network.flat.FlatNetwork.validate',
                autospec=True)
    @mock.patch('ironic.drivers.modules.fake.FakePower.validate',
                autospec=True)
    @mock.patch('ironic.drivers.modules.fake.FakePower.execute_clean_step',
                autospec=True)
    @mock.patch('ironic.drivers.modules.fake.FakeManagement.'
                'execute_clean_step', autospec=True)
    @mock.patch('ironic.drivers.modules.fake.FakeDeploy.execute_clean_step',
                autospec=True)
    def test_do_next_clean_step_with_children_by_uuid(
            self, mock_deploy, mock_mgmt, mock_power, mock_pv, mock_nv,
            mock_sps):
        child_node1 = obj_utils.create_test_node(
            self.context,
            uuid=uuidutils.generate_uuid(),
            driver='fake-hardware',
            last_error=None,
            parent_node=self.node.uuid)
        child_node2 = obj_utils.create_test_node(
            self.context,
            uuid=uuidutils.generate_uuid(),
            driver='fake-hardware',
            last_error=None,
            parent_node=self.node.uuid)
        power_on_children = {
            'step': 'power_on', 'priority': 5, 'interface': 'power',
            'execute_on_child_nodes': True,
            'limit_child_node_execution': [child_node1.uuid]}
        update_firmware_on_children = {
            'step': 'update_firmware', 'priority': 10,
            'interface': 'management',
            'execute_on_child_nodes': True,
            'limit_child_node_execution': [child_node1.uuid]}
        power_on_parent = {
            'step': 'not_power', 'priority': 15, 'interface': 'power'}
        clean_steps = [power_on_children, update_firmware_on_children,
                       power_on_parent]
        dii = self.node.driver_internal_info
        dii['clean_steps'] = clean_steps
        self.node.driver_internal_info = dii
        self.node.save()

        mock_deploy.return_value = None
        mock_mgmt.return_value = None
        mock_power.return_value = None
        child1_updated_at = str(child_node1.updated_at)

        with task_manager.acquire(
                self.context, self.node.uuid, shared=False) as task:

            cleaning.do_next_clean_step(task, 0,
                                        disable_ramdisk=True)
        self.node.refresh()
        child_node1.refresh()
        child_node2.refresh()

        # Confirm the objects *did* recieve locks.
        self.assertNotEqual(child1_updated_at, child_node1.updated_at)
        self.assertIsNone(child_node2.updated_at)

        # Confirm the child nodes have no errors
        self.assertFalse(child_node1.maintenance)
        self.assertFalse(child_node2.maintenance)
        self.assertIsNone(child_node1.last_error)
        self.assertIsNone(child_node2.last_error)
        self.assertIsNone(self.node.last_error)

        # Confirm the call counts expected
        self.assertEqual(0, mock_deploy.call_count)
        self.assertEqual(1, mock_mgmt.call_count)
        self.assertEqual(1, mock_power.call_count)
        self.assertEqual(0, mock_nv.call_count)
        self.assertEqual(0, mock_pv.call_count)
        mock_sps.assert_has_calls([
            mock.call(mock.ANY, mock.ANY, 'power on', timeout=None)])
