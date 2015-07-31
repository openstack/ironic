# Copyright 2014 Rackspace, Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import types

import mock
from oslo_config import cfg

from ironic.common import dhcp_factory
from ironic.common import exception
from ironic.common import image_service
from ironic.common import keystone
from ironic.common import pxe_utils
from ironic.common import states
from ironic.conductor import task_manager
from ironic.conductor import utils as manager_utils
from ironic.drivers.modules import agent
from ironic.drivers.modules import agent_client
from ironic.drivers.modules import fake
from ironic.drivers.modules.ilo import power as ilo_power
from ironic.drivers.modules import ipmitool
from ironic.drivers.modules.irmc import deploy as irmc_deploy
from ironic.drivers.modules.irmc import power as irmc_power
from ironic.tests.conductor import utils as mgr_utils
from ironic.tests.db import base as db_base
from ironic.tests.db import utils as db_utils
from ironic.tests.objects import utils as object_utils


INSTANCE_INFO = db_utils.get_test_agent_instance_info()
DRIVER_INFO = db_utils.get_test_agent_driver_info()
DRIVER_INTERNAL_INFO = db_utils.get_test_agent_driver_internal_info()

CONF = cfg.CONF


class TestAgentMethods(db_base.DbTestCase):
    def setUp(self):
        super(TestAgentMethods, self).setUp()
        self.node = object_utils.create_test_node(self.context,
                                                  driver='fake_agent')

    def test_build_agent_options_conf(self):
        self.config(api_url='api-url', group='conductor')
        options = agent.build_agent_options(self.node)
        self.assertEqual('api-url', options['ipa-api-url'])
        self.assertEqual('fake_agent', options['ipa-driver-name'])
        self.assertEqual(0, options['coreos.configdrive'])

    @mock.patch.object(keystone, 'get_service_url', autospec=True)
    def test_build_agent_options_keystone(self, get_url_mock):

        self.config(api_url=None, group='conductor')
        get_url_mock.return_value = 'api-url'
        options = agent.build_agent_options(self.node)
        self.assertEqual('api-url', options['ipa-api-url'])
        self.assertEqual('fake_agent', options['ipa-driver-name'])
        self.assertEqual(0, options['coreos.configdrive'])

    def test_build_agent_options_root_device_hints(self):
        self.config(api_url='api-url', group='conductor')
        self.node.properties['root_device'] = {'model': 'fake_model'}
        options = agent.build_agent_options(self.node)
        self.assertEqual('api-url', options['ipa-api-url'])
        self.assertEqual('fake_agent', options['ipa-driver-name'])
        self.assertEqual('model=fake_model', options['root_device'])

    @mock.patch.object(image_service, 'GlanceImageService', autospec=True)
    def test_build_instance_info_for_deploy_glance_image(self, glance_mock):
        i_info = self.node.instance_info
        i_info['image_source'] = '733d1c44-a2ea-414b-aca7-69decf20d810'
        self.node.instance_info = i_info
        self.node.save()

        image_info = {'checksum': 'aa', 'disk_format': 'qcow2',
                      'container_format': 'bare'}
        glance_mock.return_value.show = mock.MagicMock(spec_set=[],
                                                       return_value=image_info)

        mgr_utils.mock_the_extension_manager(driver='fake_agent')
        with task_manager.acquire(
                self.context, self.node.uuid, shared=False) as task:

            agent.build_instance_info_for_deploy(task)

            glance_mock.assert_called_once_with(version=2,
                                                context=task.context)
            glance_mock.return_value.show.assert_called_once_with(
                self.node.instance_info['image_source'])
            glance_mock.return_value.swift_temp_url.assert_called_once_with(
                image_info)

    @mock.patch.object(image_service.HttpImageService, 'validate_href',
                       autospec=True)
    def test_build_instance_info_for_deploy_nonglance_image(
            self, validate_href_mock):
        i_info = self.node.instance_info
        i_info['image_source'] = 'http://image-ref'
        i_info['image_checksum'] = 'aa'
        self.node.instance_info = i_info
        self.node.save()

        mgr_utils.mock_the_extension_manager(driver='fake_agent')
        with task_manager.acquire(
                self.context, self.node.uuid, shared=False) as task:

            info = agent.build_instance_info_for_deploy(task)

            self.assertEqual(self.node.instance_info['image_source'],
                             info['image_url'])
            validate_href_mock.assert_called_once_with(
                mock.ANY, 'http://image-ref')

    @mock.patch.object(image_service.HttpImageService, 'validate_href',
                       autospec=True)
    def test_build_instance_info_for_deploy_nonsupported_image(
            self, validate_href_mock):
        validate_href_mock.side_effect = iter(
            [exception.ImageRefValidationFailed(
                image_href='file://img.qcow2', reason='fail')])
        i_info = self.node.instance_info
        i_info['image_source'] = 'file://img.qcow2'
        i_info['image_checksum'] = 'aa'
        self.node.instance_info = i_info
        self.node.save()

        mgr_utils.mock_the_extension_manager(driver='fake_agent')
        with task_manager.acquire(
                self.context, self.node.uuid, shared=False) as task:

            self.assertRaises(exception.ImageRefValidationFailed,
                              agent.build_instance_info_for_deploy, task)


class TestAgentDeploy(db_base.DbTestCase):
    def setUp(self):
        super(TestAgentDeploy, self).setUp()
        mgr_utils.mock_the_extension_manager(driver='fake_agent')
        self.driver = agent.AgentDeploy()
        n = {
            'driver': 'fake_agent',
            'instance_info': INSTANCE_INFO,
            'driver_info': DRIVER_INFO,
            'driver_internal_info': DRIVER_INTERNAL_INFO,
        }
        self.node = object_utils.create_test_node(self.context, **n)
        self.ports = [object_utils.create_test_port(self.context,
                                                    node_id=self.node.id)]

    def test_get_properties(self):
        expected = agent.COMMON_PROPERTIES
        self.assertEqual(expected, self.driver.get_properties())

    def test_validate(self):
        with task_manager.acquire(
                self.context, self.node['uuid'], shared=False) as task:
            self.driver.validate(task)

    def test_validate_driver_info_missing_params(self):
        self.node.driver_info = {}
        self.node.save()
        with task_manager.acquire(
                self.context, self.node['uuid'], shared=False) as task:
            e = self.assertRaises(exception.MissingParameterValue,
                                  self.driver.validate, task)
        self.assertIn('driver_info.deploy_ramdisk', str(e))
        self.assertIn('driver_info.deploy_kernel', str(e))

    def test_validate_driver_info_manage_tftp_false(self):
        self.config(manage_tftp=False, group='agent')
        self.node.driver_info = {}
        self.node.save()
        with task_manager.acquire(
                self.context, self.node['uuid'], shared=False) as task:
            self.driver.validate(task)

    def test_validate_instance_info_missing_params(self):
        self.node.instance_info = {}
        self.node.save()
        with task_manager.acquire(
                self.context, self.node['uuid'], shared=False) as task:
            e = self.assertRaises(exception.MissingParameterValue,
                                  self.driver.validate, task)
        self.assertIn('instance_info.image_source', str(e))

    def test_validate_nonglance_image_no_checksum(self):
        i_info = self.node.instance_info
        i_info['image_source'] = 'http://image-ref'
        del i_info['image_checksum']
        self.node.instance_info = i_info
        self.node.save()

        with task_manager.acquire(
                self.context, self.node.uuid, shared=False) as task:
            self.assertRaises(exception.MissingParameterValue,
                              self.driver.validate, task)

    def test_validate_agent_fail_partition_image(self):
        with task_manager.acquire(
                self.context, self.node['uuid'], shared=False) as task:
            task.node.driver_internal_info['is_whole_disk_image'] = False
            self.assertRaises(exception.InvalidParameterValue,
                              self.driver.validate, task)

    def test_validate_invalid_root_device_hints(self):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            task.node.properties['root_device'] = {'size': 'not-int'}
            self.assertRaises(exception.InvalidParameterValue,
                              task.driver.deploy.validate, task)

    @mock.patch.object(agent, '_cache_tftp_images', autospec=True)
    @mock.patch.object(pxe_utils, 'create_pxe_config', autospec=True)
    @mock.patch.object(agent, '_build_pxe_config_options', autospec=True)
    @mock.patch.object(agent, '_get_tftp_image_info', autospec=True)
    def test__prepare_pxe_boot(self, pxe_info_mock, options_mock,
                               create_mock, cache_mock):
        with task_manager.acquire(
                self.context, self.node['uuid'], shared=False) as task:
            agent._prepare_pxe_boot(task)
            pxe_info_mock.assert_called_once_with(task.node)
            options_mock.assert_called_once_with(task.node, mock.ANY)
            create_mock.assert_called_once_with(
                task, mock.ANY, CONF.agent.agent_pxe_config_template)
            cache_mock.assert_called_once_with(task.context, task.node,
                                               mock.ANY)

    @mock.patch.object(agent, '_cache_tftp_images', autospec=True)
    @mock.patch.object(pxe_utils, 'create_pxe_config', autospec=True)
    @mock.patch.object(agent, '_build_pxe_config_options', autospec=True)
    @mock.patch.object(agent, '_get_tftp_image_info', autospec=True)
    def test__prepare_pxe_boot_manage_tftp_false(
            self, pxe_info_mock, options_mock, create_mock, cache_mock):
        self.config(manage_tftp=False, group='agent')
        with task_manager.acquire(
                self.context, self.node['uuid'], shared=False) as task:
            agent._prepare_pxe_boot(task)
        self.assertFalse(pxe_info_mock.called)
        self.assertFalse(options_mock.called)
        self.assertFalse(create_mock.called)
        self.assertFalse(cache_mock.called)

    @mock.patch.object(dhcp_factory.DHCPFactory, 'update_dhcp', autospec=True)
    @mock.patch('ironic.conductor.utils.node_set_boot_device', autospec=True)
    @mock.patch('ironic.conductor.utils.node_power_action', autospec=True)
    def test_deploy(self, power_mock, bootdev_mock, dhcp_mock):
        with task_manager.acquire(
                self.context, self.node['uuid'], shared=False) as task:
            dhcp_opts = pxe_utils.dhcp_options_for_instance(task)
            driver_return = self.driver.deploy(task)
            self.assertEqual(driver_return, states.DEPLOYWAIT)
            dhcp_mock.assert_called_once_with(mock.ANY, task, dhcp_opts, None)
            bootdev_mock.assert_called_once_with(task, 'pxe', persistent=True)
            power_mock.assert_called_once_with(task,
                                               states.REBOOT)

    @mock.patch('ironic.conductor.utils.node_power_action', autospec=True)
    def test_tear_down(self, power_mock):
        with task_manager.acquire(
                self.context, self.node['uuid'], shared=False) as task:
            driver_return = self.driver.tear_down(task)
            power_mock.assert_called_once_with(task, states.POWER_OFF)
            self.assertEqual(driver_return, states.DELETED)

    @mock.patch.object(pxe_utils, 'clean_up_pxe_config', autospec=True)
    @mock.patch.object(agent, 'AgentTFTPImageCache', autospec=True)
    @mock.patch('ironic.common.utils.unlink_without_raise', autospec=True)
    @mock.patch.object(agent, '_get_tftp_image_info', autospec=True)
    def test__clean_up_pxe(self, info_mock, unlink_mock, cache_mock,
                           clean_mock):
        info_mock.return_value = {'label': ['fake1', 'fake2']}
        with task_manager.acquire(
                self.context, self.node['uuid'], shared=False) as task:
            agent._clean_up_pxe(task)
            info_mock.assert_called_once_with(task.node)
            unlink_mock.assert_called_once_with('fake2')
            clean_mock.assert_called_once_with(task)

    @mock.patch.object(pxe_utils, 'clean_up_pxe_config', autospec=True)
    @mock.patch.object(agent.AgentTFTPImageCache, 'clean_up', autospec=True)
    @mock.patch('ironic.common.utils.unlink_without_raise', autospec=True)
    @mock.patch.object(agent, '_get_tftp_image_info', autospec=True)
    def test__clean_up_pxe_manage_tftp_false(
            self, info_mock, unlink_mock, cache_mock, clean_mock):
        self.config(manage_tftp=False, group='agent')
        info_mock.return_value = {'label': ['fake1', 'fake2']}
        with task_manager.acquire(
                self.context, self.node['uuid'], shared=False) as task:
            agent._clean_up_pxe(task)
            self.assertFalse(info_mock.called)
            self.assertFalse(unlink_mock.called)
            self.assertFalse(cache_mock.called)
            self.assertFalse(clean_mock.called)

    @mock.patch('ironic.dhcp.neutron.NeutronDHCPApi.delete_cleaning_ports',
                autospec=True)
    @mock.patch('ironic.dhcp.neutron.NeutronDHCPApi.create_cleaning_ports',
                autospec=True)
    @mock.patch('ironic.drivers.modules.agent._do_pxe_boot', autospec=True)
    @mock.patch('ironic.drivers.modules.agent._prepare_pxe_boot',
                autospec=True)
    def test_prepare_cleaning(self, prepare_mock, boot_mock, create_mock,
                              delete_mock):
        ports = [{'ports': self.ports}]
        create_mock.return_value = ports
        with task_manager.acquire(
                self.context, self.node['uuid'], shared=False) as task:
            self.assertEqual(states.CLEANWAIT,
                             self.driver.prepare_cleaning(task))
            prepare_mock.assert_called_once_with(task)
            boot_mock.assert_called_once_with(task, ports)
            create_mock.assert_called_once_with(mock.ANY, task)
            delete_mock.assert_called_once_with(mock.ANY, task)
            self.assertEqual(task.node.driver_internal_info.get(
                             'agent_erase_devices_iterations'), 1)

    @mock.patch('ironic.dhcp.neutron.NeutronDHCPApi.delete_cleaning_ports',
                autospec=True)
    @mock.patch('ironic.drivers.modules.agent._clean_up_pxe', autospec=True)
    @mock.patch('ironic.conductor.utils.node_power_action', autospec=True)
    def test_tear_down_cleaning(self, power_mock, cleanup_mock, neutron_mock):
        with task_manager.acquire(
                self.context, self.node['uuid'], shared=False) as task:
            self.assertIsNone(self.driver.tear_down_cleaning(task))
            power_mock.assert_called_once_with(task, states.POWER_OFF)
            cleanup_mock.assert_called_once_with(task)
            neutron_mock.assert_called_once_with(mock.ANY, task)

    @mock.patch('ironic.drivers.modules.deploy_utils.agent_get_clean_steps',
                autospec=True)
    def test_get_clean_steps(self, mock_get_clean_steps):
        # Test getting clean steps
        mock_steps = [{'priority': 10, 'interface': 'deploy',
                       'step': 'erase_devices'}]
        mock_get_clean_steps.return_value = mock_steps
        with task_manager.acquire(self.context, self.node.uuid) as task:
            steps = self.driver.get_clean_steps(task)
            mock_get_clean_steps.assert_called_once_with(task)
        self.assertEqual(mock_steps, steps)

    @mock.patch('ironic.drivers.modules.deploy_utils.agent_get_clean_steps',
                autospec=True)
    def test_get_clean_steps_config_priority(self, mock_get_clean_steps):
        # Test that we can override the priority of get clean steps
        # Use 0 because it is an edge case (false-y) and used in devstack
        self.config(agent_erase_devices_priority=0, group='agent')
        mock_steps = [{'priority': 10, 'interface': 'deploy',
                       'step': 'erase_devices'}]
        expected_steps = [{'priority': 0, 'interface': 'deploy',
                           'step': 'erase_devices'}]
        mock_get_clean_steps.return_value = mock_steps
        with task_manager.acquire(self.context, self.node.uuid) as task:
            steps = self.driver.get_clean_steps(task)
            mock_get_clean_steps.assert_called_once_with(task)
        self.assertEqual(expected_steps, steps)


class TestAgentVendor(db_base.DbTestCase):

    def setUp(self):
        super(TestAgentVendor, self).setUp()
        mgr_utils.mock_the_extension_manager(driver="fake_agent")
        self.passthru = agent.AgentVendorInterface()
        n = {
            'driver': 'fake_agent',
            'instance_info': INSTANCE_INFO,
            'driver_info': DRIVER_INFO,
            'driver_internal_info': DRIVER_INTERNAL_INFO,
        }
        self.node = object_utils.create_test_node(self.context, **n)

    def test_continue_deploy(self):
        self.node.provision_state = states.DEPLOYWAIT
        self.node.target_provision_state = states.ACTIVE
        self.node.save()
        test_temp_url = 'http://image'
        expected_image_info = {
            'urls': [test_temp_url],
            'id': 'fake-image',
            'checksum': 'checksum',
            'disk_format': 'qcow2',
            'container_format': 'bare',
        }

        client_mock = mock.MagicMock(spec_set=['prepare_image'])
        self.passthru._client = client_mock

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            self.passthru.continue_deploy(task)

            client_mock.prepare_image.assert_called_with(task.node,
                                                         expected_image_info)
            self.assertEqual(states.DEPLOYWAIT, task.node.provision_state)
            self.assertEqual(states.ACTIVE,
                             task.node.target_provision_state)

    def test_continue_deploy_image_source_is_url(self):
        self.node.provision_state = states.DEPLOYWAIT
        self.node.target_provision_state = states.ACTIVE
        self.node.save()
        test_temp_url = 'http://image'
        expected_image_info = {
            'urls': [test_temp_url],
            'id': self.node.instance_info['image_source'],
            'checksum': 'checksum',
            'disk_format': 'qcow2',
            'container_format': 'bare',
        }

        client_mock = mock.MagicMock(spec_set=['prepare_image'])
        self.passthru._client = client_mock

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            self.passthru.continue_deploy(task)

            client_mock.prepare_image.assert_called_with(task.node,
                                                         expected_image_info)
            self.assertEqual(states.DEPLOYWAIT, task.node.provision_state)
            self.assertEqual(states.ACTIVE,
                             task.node.target_provision_state)

    @mock.patch.object(manager_utils, 'node_power_action', autospec=True)
    @mock.patch.object(agent_client.AgentClient, 'power_off',
                       spec=types.FunctionType)
    @mock.patch('ironic.conductor.utils.node_set_boot_device', autospec=True)
    @mock.patch('ironic.drivers.modules.agent.AgentVendorInterface'
                '.check_deploy_success', autospec=True)
    @mock.patch.object(agent, '_clean_up_pxe', autospec=True)
    def _test_reboot_to_instance(self, clean_pxe_mock, check_deploy_mock,
                                 bootdev_mock, power_off_mock,
                                 node_power_action_mock,
                                 get_power_state_mock,
                                 uses_pxe=True):
        check_deploy_mock.return_value = None

        self.node.provision_state = states.DEPLOYWAIT
        self.node.target_provision_state = states.ACTIVE
        self.node.save()

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            get_power_state_mock.return_value = states.POWER_OFF
            task.node.driver_internal_info['is_whole_disk_image'] = True
            self.passthru.reboot_to_instance(task)

            if uses_pxe:
                clean_pxe_mock.assert_called_once_with(task)
            else:
                self.assertFalse(clean_pxe_mock.called)
            check_deploy_mock.assert_called_once_with(mock.ANY, task.node)
            bootdev_mock.assert_called_once_with(task, 'disk', persistent=True)
            power_off_mock.assert_called_once_with(task.node)
            get_power_state_mock.assert_called_once_with(task)
            node_power_action_mock.assert_called_once_with(
                task, states.POWER_ON)
            self.assertEqual(states.ACTIVE, task.node.provision_state)
            self.assertEqual(states.NOSTATE, task.node.target_provision_state)

    @mock.patch.object(fake.FakePower, 'get_power_state',
                       spec=types.FunctionType)
    def test_reboot_to_instance_fake_driver(self, get_power_state_mock):
        self._test_reboot_to_instance(
            get_power_state_mock=get_power_state_mock)

    @mock.patch.object(ipmitool.IPMIPower, 'get_power_state',
                       spec=types.FunctionType)
    def test_reboot_to_instance_agent_ipmitool_driver(
            self, get_power_state_mock):
        mgr_utils.mock_the_extension_manager(driver='agent_ipmitool')
        self.node.driver = 'agent_ipmitool'
        self.node.save()
        self._test_reboot_to_instance(
            get_power_state_mock=get_power_state_mock)

    @mock.patch.object(ilo_power.IloPower, 'get_power_state',
                       spec=types.FunctionType)
    def test_reboot_to_instance_agent_ilo_driver(self, get_power_state_mock):
        mgr_utils.mock_the_extension_manager(driver='agent_ilo')
        self.node.driver = 'agent_ilo'
        self.node.save()
        self._test_reboot_to_instance(
            get_power_state_mock=get_power_state_mock, uses_pxe=False)

    @mock.patch.object(irmc_power.IRMCPower, 'get_power_state',
                       spec=types.FunctionType)
    def test_reboot_to_instance_agent_irmc_driver(self, get_power_state_mock):
        irmc_deploy._check_share_fs_mounted_patcher.start()
        mgr_utils.mock_the_extension_manager(driver='agent_irmc')
        self.node.driver = 'agent_irmc'
        self.node.save()
        self._test_reboot_to_instance(
            get_power_state_mock=get_power_state_mock, uses_pxe=False)

    @mock.patch.object(agent_client.AgentClient, 'get_commands_status',
                       autospec=True)
    def test_deploy_has_started(self, mock_get_cmd):
        with task_manager.acquire(self.context, self.node.uuid) as task:
            mock_get_cmd.return_value = []
            self.assertFalse(self.passthru.deploy_has_started(task))

    @mock.patch.object(agent_client.AgentClient, 'get_commands_status',
                       autospec=True)
    def test_deploy_has_started_is_done(self, mock_get_cmd):
        with task_manager.acquire(self.context, self.node.uuid) as task:
            mock_get_cmd.return_value = [{'command_name': 'prepare_image',
                                          'command_status': 'SUCCESS'}]
            self.assertTrue(self.passthru.deploy_has_started(task))

    @mock.patch.object(agent_client.AgentClient, 'get_commands_status',
                       autospec=True)
    def test_deploy_has_started_did_start(self, mock_get_cmd):
        with task_manager.acquire(self.context, self.node.uuid) as task:
            mock_get_cmd.return_value = [{'command_name': 'prepare_image',
                                          'command_status': 'RUNNING'}]
            self.assertTrue(self.passthru.deploy_has_started(task))

    @mock.patch.object(agent_client.AgentClient, 'get_commands_status',
                       autospec=True)
    def test_deploy_has_started_multiple_commands(self, mock_get_cmd):
        with task_manager.acquire(self.context, self.node.uuid) as task:
            mock_get_cmd.return_value = [{'command_name': 'cache_image',
                                          'command_status': 'SUCCESS'},
                                         {'command_name': 'prepare_image',
                                          'command_status': 'RUNNING'}]
            self.assertTrue(self.passthru.deploy_has_started(task))

    @mock.patch.object(agent_client.AgentClient, 'get_commands_status',
                       autospec=True)
    def test_deploy_has_started_other_commands(self, mock_get_cmd):
        with task_manager.acquire(self.context, self.node.uuid) as task:
            mock_get_cmd.return_value = [{'command_name': 'cache_image',
                                          'command_status': 'SUCCESS'}]
            self.assertFalse(self.passthru.deploy_has_started(task))

    @mock.patch.object(agent_client.AgentClient, 'get_commands_status',
                       autospec=True)
    def test_deploy_is_done(self, mock_get_cmd):
        with task_manager.acquire(self.context, self.node.uuid) as task:
            mock_get_cmd.return_value = [{'command_name': 'prepare_image',
                                          'command_status': 'SUCCESS'}]
            self.assertTrue(self.passthru.deploy_is_done(task))

    @mock.patch.object(agent_client.AgentClient, 'get_commands_status',
                       autospec=True)
    def test_deploy_is_done_empty_response(self, mock_get_cmd):
        with task_manager.acquire(self.context, self.node.uuid) as task:
            mock_get_cmd.return_value = []
            self.assertFalse(self.passthru.deploy_is_done(task))

    @mock.patch.object(agent_client.AgentClient, 'get_commands_status',
                       autospec=True)
    def test_deploy_is_done_race(self, mock_get_cmd):
        with task_manager.acquire(self.context, self.node.uuid) as task:
            mock_get_cmd.return_value = [{'command_name': 'some_other_command',
                                          'command_status': 'SUCCESS'}]
            self.assertFalse(self.passthru.deploy_is_done(task))

    @mock.patch.object(agent_client.AgentClient, 'get_commands_status',
                       autospec=True)
    def test_deploy_is_done_still_running(self, mock_get_cmd):
        with task_manager.acquire(self.context, self.node.uuid) as task:
            mock_get_cmd.return_value = [{'command_name': 'prepare_image',
                                          'command_status': 'RUNNING'}]
            self.assertFalse(self.passthru.deploy_is_done(task))

    def _build_pxe_config_options(self, root_device_hints=False):
        self.config(api_url='api-url', group='conductor')
        self.config(agent_pxe_append_params='foo bar', group='agent')

        if root_device_hints:
            self.node.properties['root_device'] = {'model': 'FakeModel'}

        pxe_info = {
            'deploy_kernel': ('glance://deploy-kernel',
                              'fake-node/deploy_kernel'),
            'deploy_ramdisk': ('glance://deploy-ramdisk',
                               'fake-node/deploy_ramdisk'),
        }
        options = agent._build_pxe_config_options(self.node, pxe_info)
        expected = {'deployment_aki_path': 'fake-node/deploy_kernel',
                    'deployment_ari_path': 'fake-node/deploy_ramdisk',
                    'ipa-api-url': 'api-url',
                    'ipa-driver-name': u'fake_agent',
                    'coreos.configdrive': 0,
                    'pxe_append_params': 'foo bar'}

        if root_device_hints:
            expected['root_device'] = 'model=FakeModel'

        self.assertEqual(expected, options)

    def test__build_pxe_config_options(self):
        self._build_pxe_config_options()

    def test__build_pxe_config_options_root_device_hints(self):
        self._build_pxe_config_options(root_device_hints=True)
