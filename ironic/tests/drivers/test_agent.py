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

import mock
from oslo_config import cfg

from ironic.common import dhcp_factory
from ironic.common import exception
from ironic.common import image_service
from ironic.common import keystone
from ironic.common import pxe_utils
from ironic.common import states
from ironic.conductor import task_manager
from ironic.drivers.modules import agent
from ironic.drivers.modules import agent_client
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

    @mock.patch.object(keystone, 'get_service_url')
    def test_build_agent_options_keystone(self, get_url_mock):

        self.config(api_url=None, group='conductor')
        get_url_mock.return_value = 'api-url'
        options = agent.build_agent_options(self.node)
        self.assertEqual('api-url', options['ipa-api-url'])
        self.assertEqual('fake_agent', options['ipa-driver-name'])

    def test_build_agent_options_root_device_hints(self):
        self.config(api_url='api-url', group='conductor')
        self.node.properties['root_device'] = {'model': 'fake_model'}
        options = agent.build_agent_options(self.node)
        self.assertEqual('api-url', options['ipa-api-url'])
        self.assertEqual('fake_agent', options['ipa-driver-name'])
        self.assertEqual('model=fake_model', options['root_device'])

    @mock.patch.object(image_service, 'GlanceImageService')
    def test_build_instance_info_for_deploy_glance_image(self, glance_mock):
        i_info = self.node.instance_info
        i_info['image_source'] = 'image-uuid'
        self.node.instance_info = i_info
        self.node.save()

        image_info = {'checksum': 'aa', 'disk_format': 'qcow2',
                      'container_format': 'bare'}
        glance_mock.return_value.show = mock.Mock(return_value=image_info)

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

    @mock.patch.object(image_service.HttpImageService, 'validate_href')
    def test_build_instance_info_for_deploy_nonglance_image(self,
            validate_href_mock):
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
            validate_href_mock.assert_called_once_with('http://image-ref')

    @mock.patch.object(image_service.HttpImageService, 'validate_href')
    def test_build_instance_info_for_deploy_nonsupported_image(self,
            validate_href_mock):
        validate_href_mock.side_effect = exception.ImageRefValidationFailed(
            image_href='file://img.qcow2', reason='fail')
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

    def test_validate_invalid_root_device_hints(self):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            task.node.properties['root_device'] = {'size': 'not-int'}
            self.assertRaises(exception.InvalidParameterValue,
                              task.driver.deploy.validate, task)

    @mock.patch.object(dhcp_factory.DHCPFactory, 'update_dhcp')
    @mock.patch('ironic.conductor.utils.node_set_boot_device')
    @mock.patch('ironic.conductor.utils.node_power_action')
    def test_deploy(self, power_mock, bootdev_mock, dhcp_mock):
        with task_manager.acquire(
                self.context, self.node['uuid'], shared=False) as task:
            dhcp_opts = pxe_utils.dhcp_options_for_instance(task)
            driver_return = self.driver.deploy(task)
            self.assertEqual(driver_return, states.DEPLOYWAIT)
            dhcp_mock.assert_called_once_with(task, dhcp_opts, None)
            bootdev_mock.assert_called_once_with(task, 'pxe', persistent=True)
            power_mock.assert_called_once_with(task,
                                               states.REBOOT)

    @mock.patch('ironic.conductor.utils.node_power_action')
    def test_tear_down(self, power_mock):
        with task_manager.acquire(
                self.context, self.node['uuid'], shared=False) as task:
            driver_return = self.driver.tear_down(task)
            power_mock.assert_called_once_with(task, states.POWER_OFF)
            self.assertEqual(driver_return, states.DELETED)

    @mock.patch('ironic.dhcp.neutron.NeutronDHCPApi.delete_cleaning_ports')
    @mock.patch('ironic.dhcp.neutron.NeutronDHCPApi.create_cleaning_ports')
    @mock.patch('ironic.drivers.modules.agent._do_pxe_boot')
    @mock.patch('ironic.drivers.modules.agent._prepare_pxe_boot')
    def test_prepare_cleaning(self, prepare_mock, boot_mock, create_mock,
                              delete_mock):
        ports = [{'ports': self.ports}]
        create_mock.return_value = ports
        with task_manager.acquire(
                self.context, self.node['uuid'], shared=False) as task:
            self.assertEqual(states.CLEANING,
                             self.driver.prepare_cleaning(task))
            prepare_mock.assert_called_once_with(task)
            boot_mock.assert_called_once_with(task, ports)
            create_mock.assert_called_once()
            delete_mock.assert_called_once()

    @mock.patch('ironic.dhcp.neutron.NeutronDHCPApi.delete_cleaning_ports')
    @mock.patch('ironic.drivers.modules.agent._clean_up_pxe')
    @mock.patch('ironic.conductor.utils.node_power_action')
    def test_tear_down_cleaning(self, power_mock, cleanup_mock, neutron_mock):
        with task_manager.acquire(
                self.context, self.node['uuid'], shared=False) as task:
            self.assertIsNone(self.driver.tear_down_cleaning(task))
            power_mock.assert_called_once_with(task, states.POWER_OFF)
            cleanup_mock.assert_called_once_with(task)
            neutron_mock.assert_called_once()

    @mock.patch('ironic.drivers.modules.deploy_utils.agent_get_clean_steps')
    def test_get_clean_steps(self, mock_get_clean_steps):
        # Test getting clean steps
        mock_steps = [{'priority': 10, 'interface': 'deploy',
                       'step': 'erase_devices'}]
        mock_get_clean_steps.return_value = mock_steps
        with task_manager.acquire(self.context, self.node.uuid) as task:
            steps = self.driver.get_clean_steps(task)
            mock_get_clean_steps.assert_called_once_with(task)
        self.assertEqual(mock_steps, steps)

    @mock.patch('ironic.drivers.modules.deploy_utils.agent_get_clean_steps')
    def test_get_clean_steps_config_priority(self, mock_get_clean_steps):
        # Test that we can override the priority of get clean steps
        self.config(agent_erase_devices_priority=20, group='agent')
        mock_steps = [{'priority': 10, 'interface': 'deploy',
                       'step': 'erase_devices'}]
        expected_steps = [{'priority': 20, 'interface': 'deploy',
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

        client_mock = mock.Mock()
        self.passthru._client = client_mock

        with task_manager.acquire(self.context, self.node.uuid,
                                      shared=False) as task:
            self.passthru.continue_deploy(task)

            client_mock.prepare_image.assert_called_with(task.node,
                expected_image_info)
            self.assertEqual(states.DEPLOYING, task.node.provision_state)
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

        client_mock = mock.Mock()
        self.passthru._client = client_mock

        with task_manager.acquire(self.context, self.node.uuid,
                                      shared=False) as task:
            self.passthru.continue_deploy(task)

            client_mock.prepare_image.assert_called_with(task.node,
                expected_image_info)
            self.assertEqual(states.DEPLOYING, task.node.provision_state)
            self.assertEqual(states.ACTIVE,
                             task.node.target_provision_state)

    @mock.patch('ironic.conductor.utils.node_power_action')
    @mock.patch('ironic.conductor.utils.node_set_boot_device')
    @mock.patch('ironic.drivers.modules.agent.AgentVendorInterface'
                '._check_deploy_success')
    def test_reboot_to_instance(self, check_deploy_mock, bootdev_mock,
                                 power_mock):
        check_deploy_mock.return_value = None

        self.node.provision_state = states.DEPLOYING
        self.node.target_provision_state = states.ACTIVE
        self.node.save()

        with task_manager.acquire(self.context, self.node.uuid,
                                      shared=False) as task:
            self.passthru.reboot_to_instance(task)

            check_deploy_mock.assert_called_once_with(task.node)
            bootdev_mock.assert_called_once_with(task, 'disk', persistent=True)
            power_mock.assert_called_once_with(task, states.REBOOT)
            self.assertEqual(states.ACTIVE, task.node.provision_state)
            self.assertEqual(states.NOSTATE, task.node.target_provision_state)

    @mock.patch.object(agent_client.AgentClient, 'get_commands_status')
    def test_deploy_is_done(self, mock_get_cmd):
        with task_manager.acquire(self.context, self.node.uuid) as task:
            mock_get_cmd.return_value = [{'command_name': 'prepare_image',
                                          'command_status': 'SUCCESS'}]
            self.assertTrue(self.passthru.deploy_is_done(task))

    @mock.patch.object(agent_client.AgentClient, 'get_commands_status')
    def test_deploy_is_done_empty_response(self, mock_get_cmd):
        with task_manager.acquire(self.context, self.node.uuid) as task:
            mock_get_cmd.return_value = []
            self.assertFalse(self.passthru.deploy_is_done(task))

    @mock.patch.object(agent_client.AgentClient, 'get_commands_status')
    def test_deploy_is_done_race(self, mock_get_cmd):
        with task_manager.acquire(self.context, self.node.uuid) as task:
            mock_get_cmd.return_value = [{'command_name': 'some_other_command',
                                          'command_status': 'SUCCESS'}]
            self.assertFalse(self.passthru.deploy_is_done(task))

    @mock.patch.object(agent_client.AgentClient, 'get_commands_status')
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
                    'pxe_append_params': 'foo bar'}

        if root_device_hints:
            expected['root_device'] = 'model=FakeModel'

        self.assertEqual(expected, options)

    def test__build_pxe_config_options(self):
        self._build_pxe_config_options()

    def test__build_pxe_config_options_root_device_hints(self):
        self._build_pxe_config_options(root_device_hints=True)
