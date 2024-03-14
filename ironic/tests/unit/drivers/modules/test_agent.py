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

from unittest import mock

from oslo_config import cfg

from ironic.common import dhcp_factory
from ironic.common import exception
from ironic.common import images
from ironic.common import raid
from ironic.common import states
from ironic.conductor import task_manager
from ironic.conductor import utils as manager_utils
from ironic.drivers import base as drivers_base
from ironic.drivers.modules import agent
from ironic.drivers.modules import agent_base
from ironic.drivers.modules import agent_client
from ironic.drivers.modules import boot_mode_utils
from ironic.drivers.modules import deploy_utils
from ironic.drivers.modules import fake
from ironic.drivers.modules.network import flat as flat_network
from ironic.drivers.modules.network import neutron as neutron_network
from ironic.drivers.modules import pxe
from ironic.drivers.modules.storage import noop as noop_storage
from ironic.tests.unit.db import base as db_base
from ironic.tests.unit.db import utils as db_utils
from ironic.tests.unit.objects import utils as object_utils


INSTANCE_INFO = db_utils.get_test_agent_instance_info()
DRIVER_INFO = db_utils.get_test_agent_driver_info()
DRIVER_INTERNAL_INFO = db_utils.get_test_agent_driver_internal_info()

CONF = cfg.CONF


class TestAgentMethods(db_base.DbTestCase):
    def setUp(self):
        super(TestAgentMethods, self).setUp()
        self.node = object_utils.create_test_node(self.context,
                                                  boot_interface='pxe',
                                                  deploy_interface='direct')
        dhcp_factory.DHCPFactory._dhcp_provider = None

    @mock.patch.object(images, 'image_show', autospec=True)
    def test_check_image_size(self, show_mock):
        show_mock.return_value = {
            'size': 10 * 1024 * 1024,
            'disk_format': 'qcow2',
        }
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.node.properties['memory_mb'] = 10
            task.node.instance_info['image_source'] = 'fake-image'
            agent.check_image_size(task)
            show_mock.assert_called_once_with(self.context, 'fake-image')

    @mock.patch.object(images, 'image_show', autospec=True)
    def test_check_image_size_without_memory_mb(self, show_mock):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.node.properties.pop('memory_mb', None)
            task.node.instance_info['image_source'] = 'fake-image'
            agent.check_image_size(task)
            self.assertFalse(show_mock.called)

    @mock.patch.object(images, 'image_show', autospec=True)
    def test_check_image_size_fail(self, show_mock):
        show_mock.return_value = {
            'size': 11 * 1024 * 1024,
            'disk_format': 'qcow2',
        }
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.node.properties['memory_mb'] = 10
            task.node.instance_info['image_source'] = 'fake-image'
            self.assertRaises(exception.InvalidParameterValue,
                              agent.check_image_size,
                              task)
            show_mock.assert_called_once_with(self.context, 'fake-image')

    @mock.patch.object(images, 'image_show', autospec=True)
    def test_check_image_size_fail_by_agent_consumed_memory(self, show_mock):
        self.config(memory_consumed_by_agent=2, group='agent')
        show_mock.return_value = {
            'size': 9 * 1024 * 1024,
            'disk_format': 'qcow2',
        }
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.node.properties['memory_mb'] = 10
            task.node.instance_info['image_source'] = 'fake-image'
            self.assertRaises(exception.InvalidParameterValue,
                              agent.check_image_size,
                              task)
            show_mock.assert_called_once_with(self.context, 'fake-image')

    @mock.patch.object(images, 'image_show', autospec=True)
    def test_check_image_size_raw_stream_enabled(self, show_mock):
        CONF.set_override('stream_raw_images', True, 'agent')
        # Image is bigger than memory but it's raw and will be streamed
        # so the test should pass
        show_mock.return_value = {
            'size': 15 * 1024 * 1024,
            'disk_format': 'raw',
        }
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.node.properties['memory_mb'] = 10
            task.node.instance_info['image_source'] = 'fake-image'
            agent.check_image_size(task)
            show_mock.assert_called_once_with(self.context, 'fake-image')

    @mock.patch.object(images, 'image_show', autospec=True)
    def test_check_image_size_raw_stream_enabled_format_raw(self, show_mock):
        CONF.set_override('stream_raw_images', True, 'agent')
        # Image is bigger than memory but it's raw and will be streamed
        # so the test should pass
        show_mock.return_value = {
            'size': 15 * 1024 * 1024,
        }
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.node.properties['memory_mb'] = 10
            task.node.instance_info['image_source'] = 'fake-image'
            task.node.instance_info['image_disk_format'] = 'raw'
            agent.check_image_size(task)
            show_mock.assert_called_once_with(self.context, 'fake-image')

    @mock.patch.object(images, 'image_show', autospec=True)
    def test_check_image_size_raw_stream_enabled_format_qcow2(self, show_mock):
        CONF.set_override('stream_raw_images', True, 'agent')
        # Image is bigger than memory and won't be streamed
        show_mock.return_value = {
            'size': 15 * 1024 * 1024,
        }
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.node.properties['memory_mb'] = 10
            task.node.instance_info['image_source'] = 'fake-image'
            task.node.instance_info['image_disk_format'] = 'qcow2'
            self.assertRaises(exception.InvalidParameterValue,
                              agent.check_image_size,
                              task)
            show_mock.assert_called_once_with(self.context, 'fake-image')

    @mock.patch.object(images, 'image_show', autospec=True)
    def test_check_image_size_raw_stream_disabled(self, show_mock):
        CONF.set_override('stream_raw_images', False, 'agent')
        show_mock.return_value = {
            'size': 15 * 1024 * 1024,
            'disk_format': 'raw',
        }
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.node.properties['memory_mb'] = 10
            task.node.instance_info['image_source'] = 'fake-image'
            # Image is raw but stream is disabled, so test should fail since
            # the image is bigger than the RAM size
            self.assertRaises(exception.InvalidParameterValue,
                              agent.check_image_size,
                              task)
            show_mock.assert_called_once_with(self.context, 'fake-image')

    @mock.patch.object(deploy_utils, 'check_for_missing_params', autospec=True)
    def test_validate_http_provisioning_http_image(self, utils_mock):
        i_info = self.node.instance_info
        i_info['image_source'] = 'http://image-ref'
        self.node.instance_info = i_info
        agent.validate_http_provisioning_configuration(self.node)
        utils_mock.assert_not_called()

    @mock.patch.object(deploy_utils, 'check_for_missing_params', autospec=True)
    def test_validate_http_provisioning_not_http(self, utils_mock):
        CONF.set_override('image_download_source', 'swift', group='agent')
        i_info = self.node.instance_info
        i_info['image_source'] = '0448fa34-4db1-407b-a051-6357d5f86c59'
        self.node.instance_info = i_info
        agent.validate_http_provisioning_configuration(self.node)
        utils_mock.assert_not_called()

    def test_validate_http_provisioning_missing_args(self):
        CONF.set_override('http_url', None, group='deploy')
        i_info = self.node.instance_info
        i_info['image_source'] = '0448fa34-4db1-407b-a051-6357d5f86c59'
        self.node.instance_info = i_info
        self.assertRaisesRegex(exception.MissingParameterValue,
                               'failed to validate http provisioning',
                               agent.validate_http_provisioning_configuration,
                               self.node)

    def test_validate_http_provisioning_missing_args_file(self):
        CONF.set_override('http_url', None, group='deploy')
        i_info = self.node.instance_info
        i_info['image_source'] = 'file://image-ref'
        self.node.instance_info = i_info
        self.assertRaisesRegex(exception.MissingParameterValue,
                               'failed to validate http provisioning',
                               agent.validate_http_provisioning_configuration,
                               self.node)

    def test_validate_http_provisioning_missing_args_local_http(self):
        CONF.set_override('image_download_source', 'local', group='agent')
        CONF.set_override('http_url', None, group='deploy')
        i_info = self.node.instance_info
        i_info['image_source'] = 'http://image-ref'
        self.node.instance_info = i_info
        self.assertRaisesRegex(exception.MissingParameterValue,
                               'failed to validate http provisioning',
                               agent.validate_http_provisioning_configuration,
                               self.node)

    def test_validate_http_provisioning_missing_args_local_via_node(self):
        CONF.set_override('http_url', None, group='deploy')
        i_info = self.node.instance_info
        i_info['image_source'] = 'http://image-ref'
        i_info['image_download_source'] = 'local'
        self.node.instance_info = i_info
        self.assertRaisesRegex(exception.MissingParameterValue,
                               'failed to validate http provisioning',
                               agent.validate_http_provisioning_configuration,
                               self.node)

    def test_validate_http_provisioning_invalid_image_download_source(self):
        CONF.set_override('http_url', None, group='deploy')
        self.node.instance_info['image_source'] = 'http://image-ref'
        self.node.instance_info['image_download_source'] = 'fridge'
        self.assertRaisesRegex(exception.InvalidParameterValue, 'fridge',
                               agent.validate_http_provisioning_configuration,
                               self.node)

    def test_validate_http_provisioning_invalid_image_download_source2(self):
        CONF.set_override('http_url', None, group='deploy')
        self.node.instance_info['image_source'] = 'http://image-ref'
        self.node.driver_info['image_download_source'] = 'fridge'
        self.assertRaisesRegex(exception.InvalidParameterValue, 'fridge',
                               agent.validate_http_provisioning_configuration,
                               self.node)


class CommonTestsMixin:
    "Tests for methods shared between CustomAgentDeploy and AgentDeploy."""

    @mock.patch.object(pxe.PXEBoot, 'prepare_instance', autospec=True)
    @mock.patch('ironic.conductor.utils.node_power_action', autospec=True)
    def test_deploy(self, power_mock, mock_pxe_instance):
        with task_manager.acquire(
                self.context, self.node['uuid'], shared=False) as task:
            driver_return = self.driver.deploy(task)
            self.assertEqual(driver_return, states.DEPLOYWAIT)
            power_mock.assert_called_once_with(task, states.REBOOT)
            self.assertFalse(mock_pxe_instance.called)

    @mock.patch.object(pxe.PXEBoot, 'prepare_instance', autospec=True)
    @mock.patch('ironic.conductor.utils.node_power_action', autospec=True)
    def test_deploy_with_deployment_reboot(self, power_mock,
                                           mock_pxe_instance):
        driver_internal_info = self.node.driver_internal_info
        driver_internal_info['deployment_reboot'] = True
        self.node.driver_internal_info = driver_internal_info
        self.node.save()
        with task_manager.acquire(
                self.context, self.node['uuid'], shared=False) as task:
            driver_return = self.driver.deploy(task)
            self.assertEqual(driver_return, states.DEPLOYWAIT)
            self.assertFalse(power_mock.called)
            self.assertFalse(mock_pxe_instance.called)
            self.assertNotIn(
                'deployment_reboot', task.node.driver_internal_info)

    @mock.patch.object(manager_utils, 'node_power_action', autospec=True)
    @mock.patch.object(noop_storage.NoopStorage, 'should_write_image',
                       autospec=True)
    def test_deploy_storage_should_write_image_false(
            self, mock_write, mock_power):
        mock_write.return_value = False
        self.node.provision_state = states.DEPLOYING
        self.node.deploy_step = {
            'step': 'deploy', 'priority': 50, 'interface': 'deploy'}
        self.node.save()
        with task_manager.acquire(
                self.context, self.node['uuid'], shared=False) as task:
            driver_return = self.driver.deploy(task)
            self.assertIsNone(driver_return)
            self.assertFalse(mock_power.called)

    @mock.patch.object(agent.CustomAgentDeploy, 'refresh_steps',
                       autospec=True)
    @mock.patch('ironic.conductor.utils.is_fast_track', autospec=True)
    @mock.patch.object(pxe.PXEBoot, 'prepare_instance', autospec=True)
    @mock.patch('ironic.conductor.utils.node_power_action', autospec=True)
    def test_deploy_fast_track(self, power_mock, mock_pxe_instance,
                               mock_is_fast_track, refresh_mock):
        mock_is_fast_track.return_value = True
        self.node.target_provision_state = states.ACTIVE
        self.node.provision_state = states.DEPLOYING
        self.node.save()
        with task_manager.acquire(
                self.context, self.node['uuid'], shared=False) as task:
            result = self.driver.deploy(task)
            self.assertIsNone(result)
            self.assertFalse(power_mock.called)
            self.assertFalse(mock_pxe_instance.called)
            self.assertEqual(states.DEPLOYING, task.node.provision_state)
            self.assertEqual(states.ACTIVE,
                             task.node.target_provision_state)
            refresh_mock.assert_called_once_with(self.driver, task, 'deploy')

    @mock.patch.object(deploy_utils, 'destroy_http_instance_images',
                       autospec=True)
    @mock.patch('ironic.common.dhcp_factory.DHCPFactory', autospec=True)
    @mock.patch.object(pxe.PXEBoot, 'clean_up_instance', autospec=True)
    @mock.patch.object(pxe.PXEBoot, 'clean_up_ramdisk', autospec=True)
    def test_clean_up(self, pxe_clean_up_ramdisk_mock,
                      pxe_clean_up_instance_mock, dhcp_factor_mock,
                      destroy_images_mock):
        with task_manager.acquire(
                self.context, self.node['uuid'], shared=False) as task:
            self.driver.clean_up(task)
            pxe_clean_up_ramdisk_mock.assert_called_once_with(
                task.driver.boot, task)
            pxe_clean_up_instance_mock.assert_called_once_with(
                task.driver.boot, task)
            dhcp_factor_mock.assert_called_once_with()
            destroy_images_mock.assert_called_once_with(task.node)


class TestCustomAgentDeploy(CommonTestsMixin, db_base.DbTestCase):
    def setUp(self):
        super(TestCustomAgentDeploy, self).setUp()
        self.config(enabled_deploy_interfaces=['direct', 'custom-agent'])
        self.driver = agent.CustomAgentDeploy()
        # NOTE(TheJulia): We explicitly set the noop storage interface as the
        # default below for deployment tests in order to raise any change
        # in the default which could be a breaking behavior change
        # as the storage interface is explicitly an "opt-in" interface.
        n = {
            'boot_interface': 'pxe',
            'deploy_interface': 'custom-agent',
            'instance_info': {},
            'driver_info': DRIVER_INFO,
            'driver_internal_info': DRIVER_INTERNAL_INFO,
            'storage_interface': 'noop',
            'network_interface': 'noop'
        }
        self.node = object_utils.create_test_node(self.context, **n)
        self.ports = [
            object_utils.create_test_port(self.context, node_id=self.node.id)]
        dhcp_factory.DHCPFactory._dhcp_provider = None

    def test_get_properties(self):
        expected = agent.COMMON_PROPERTIES
        self.assertEqual(expected, self.driver.get_properties())

    @mock.patch.object(agent, 'validate_http_provisioning_configuration',
                       autospec=True)
    @mock.patch.object(deploy_utils, 'validate_capabilities',
                       spec_set=True, autospec=True)
    @mock.patch.object(images, 'image_show', autospec=True)
    @mock.patch.object(pxe.PXEBoot, 'validate', autospec=True)
    def test_validate(self, pxe_boot_validate_mock, show_mock,
                      validate_capability_mock, validate_http_mock):
        with task_manager.acquire(
                self.context, self.node['uuid'], shared=False) as task:
            self.driver.validate(task)
            pxe_boot_validate_mock.assert_called_once_with(
                task.driver.boot, task)
            validate_capability_mock.assert_called_once_with(task.node)
            # No images required for custom-agent
            show_mock.assert_not_called()
            validate_http_mock.assert_not_called()

    @mock.patch.object(noop_storage.NoopStorage, 'attach_volumes',
                       autospec=True)
    @mock.patch.object(deploy_utils, 'populate_storage_driver_internal_info',
                       autospec=True)
    @mock.patch.object(pxe.PXEBoot, 'prepare_ramdisk', autospec=True)
    @mock.patch.object(deploy_utils, 'build_agent_options', autospec=True)
    @mock.patch.object(deploy_utils, 'build_instance_info_for_deploy',
                       autospec=True)
    @mock.patch.object(flat_network.FlatNetwork, 'add_provisioning_network',
                       spec_set=True, autospec=True)
    @mock.patch.object(flat_network.FlatNetwork,
                       'unconfigure_tenant_networks',
                       spec_set=True, autospec=True)
    @mock.patch.object(flat_network.FlatNetwork, 'validate',
                       spec_set=True, autospec=True)
    def test_prepare(
            self, validate_net_mock,
            unconfigure_tenant_net_mock, add_provisioning_net_mock,
            build_instance_info_mock, build_options_mock,
            pxe_prepare_ramdisk_mock, storage_driver_info_mock,
            storage_attach_volumes_mock):
        node = self.node
        node.network_interface = 'flat'
        node.save()
        with task_manager.acquire(
                self.context, self.node['uuid'], shared=False) as task:
            task.node.provision_state = states.DEPLOYING
            build_options_mock.return_value = {'a': 'b'}
            self.driver.prepare(task)
            storage_driver_info_mock.assert_called_once_with(task)
            validate_net_mock.assert_called_once_with(mock.ANY, task)
            add_provisioning_net_mock.assert_called_once_with(mock.ANY, task)
            unconfigure_tenant_net_mock.assert_called_once_with(mock.ANY, task)
            storage_attach_volumes_mock.assert_called_once_with(
                task.driver.storage, task)
            build_instance_info_mock.assert_not_called()
            build_options_mock.assert_called_once_with(task.node)
            pxe_prepare_ramdisk_mock.assert_called_once_with(
                task.driver.boot, task, {'a': 'b'})

    @mock.patch('ironic.conductor.utils.is_fast_track', autospec=True)
    @mock.patch.object(noop_storage.NoopStorage, 'attach_volumes',
                       autospec=True)
    @mock.patch.object(deploy_utils, 'populate_storage_driver_internal_info',
                       autospec=True)
    @mock.patch.object(pxe.PXEBoot, 'prepare_ramdisk', autospec=True)
    @mock.patch.object(deploy_utils, 'build_agent_options', autospec=True)
    @mock.patch.object(deploy_utils, 'build_instance_info_for_deploy',
                       autospec=True)
    @mock.patch.object(flat_network.FlatNetwork, 'add_provisioning_network',
                       spec_set=True, autospec=True)
    @mock.patch.object(flat_network.FlatNetwork,
                       'unconfigure_tenant_networks',
                       spec_set=True, autospec=True)
    @mock.patch.object(flat_network.FlatNetwork, 'validate',
                       spec_set=True, autospec=True)
    def test_prepare_fast_track(
            self, validate_net_mock,
            unconfigure_tenant_net_mock, add_provisioning_net_mock,
            build_instance_info_mock, build_options_mock,
            pxe_prepare_ramdisk_mock, storage_driver_info_mock,
            storage_attach_volumes_mock, is_fast_track_mock):
        # TODO(TheJulia): We should revisit this test. Smartnic
        # support didn't wire in tightly on testing for power in
        # these tests, and largely fast_track impacts power operations.
        node = self.node
        node.network_interface = 'flat'
        node.save()
        is_fast_track_mock.return_value = True
        with task_manager.acquire(
                self.context, self.node['uuid'], shared=False) as task:
            task.node.provision_state = states.DEPLOYING
            build_options_mock.return_value = {'a': 'b'}
            self.driver.prepare(task)
            storage_driver_info_mock.assert_called_once_with(task)
            validate_net_mock.assert_called_once_with(mock.ANY, task)
            add_provisioning_net_mock.assert_called_once_with(mock.ANY, task)
            unconfigure_tenant_net_mock.assert_called_once_with(mock.ANY, task)
            self.assertTrue(storage_attach_volumes_mock.called)
            self.assertFalse(build_instance_info_mock.called)
            # TODO(TheJulia): We should likely consider executing the
            # next two methods at some point in order to facilitate
            # continuity. While not explicitly required for this feature
            # to work, reboots as part of deployment would need the ramdisk
            # present and ready.
            self.assertFalse(build_options_mock.called)


class TestAgentDeploy(CommonTestsMixin, db_base.DbTestCase):
    def setUp(self):
        super(TestAgentDeploy, self).setUp()
        self.driver = agent.AgentDeploy()
        # NOTE(TheJulia): We explicitly set the noop storage interface as the
        # default below for deployment tests in order to raise any change
        # in the default which could be a breaking behavior change
        # as the storage interface is explicitly an "opt-in" interface.
        n = {
            'boot_interface': 'pxe',
            'deploy_interface': 'direct',
            'instance_info': INSTANCE_INFO,
            'driver_info': DRIVER_INFO,
            'driver_internal_info': DRIVER_INTERNAL_INFO,
            'storage_interface': 'noop',
            'network_interface': 'noop'
        }
        self.node = object_utils.create_test_node(self.context, **n)
        self.ports = [
            object_utils.create_test_port(self.context, node_id=self.node.id)]
        dhcp_factory.DHCPFactory._dhcp_provider = None
        CONF.set_override('http_url', 'http://example.com', group='deploy')

    def test_get_properties(self):
        expected = agent.COMMON_PROPERTIES
        self.assertEqual(expected, self.driver.get_properties())

    @mock.patch.object(agent, 'validate_http_provisioning_configuration',
                       autospec=True)
    @mock.patch.object(deploy_utils, 'validate_capabilities',
                       spec_set=True, autospec=True)
    @mock.patch.object(pxe.PXEBoot, 'validate', autospec=True)
    def test_validate(self, pxe_boot_validate_mock,
                      validate_capability_mock, validate_http_mock):
        with task_manager.acquire(
                self.context, self.node['uuid'], shared=False) as task:
            self.driver.validate(task)
            pxe_boot_validate_mock.assert_called_once_with(
                task.driver.boot, task)
            validate_capability_mock.assert_called_once_with(task.node)
            validate_http_mock.assert_called_once_with(task.node)

    @mock.patch.object(agent, 'validate_http_provisioning_configuration',
                       autospec=True)
    @mock.patch.object(deploy_utils, 'validate_capabilities',
                       spec_set=True, autospec=True)
    @mock.patch.object(pxe.PXEBoot, 'validate', autospec=True)
    def test_validate_driver_info_manage_agent_boot_false(
            self, pxe_boot_validate_mock, validate_capability_mock,
            validate_http_mock):

        self.config(manage_agent_boot=False, group='agent')
        self.node.driver_info = {}
        self.node.save()
        with task_manager.acquire(
                self.context, self.node['uuid'], shared=False) as task:
            self.driver.validate(task)
            self.assertFalse(pxe_boot_validate_mock.called)
            validate_capability_mock.assert_called_once_with(task.node)
            validate_http_mock.assert_called_once_with(task.node)

    @mock.patch.object(pxe.PXEBoot, 'validate', autospec=True)
    def test_validate_instance_info_missing_params(
            self, pxe_boot_validate_mock):
        self.node.instance_info = {}
        self.node.save()
        with task_manager.acquire(
                self.context, self.node['uuid'], shared=False) as task:
            e = self.assertRaises(exception.MissingParameterValue,
                                  self.driver.validate, task)
            pxe_boot_validate_mock.assert_called_once_with(
                task.driver.boot, task)

        self.assertIn('instance_info.image_source', str(e))

    @mock.patch.object(pxe.PXEBoot, 'validate', autospec=True)
    def test_validate_nonglance_image_no_checksum(
            self, pxe_boot_validate_mock):
        i_info = self.node.instance_info
        i_info['image_source'] = 'http://image-ref'
        del i_info['image_checksum']
        self.node.instance_info = i_info
        self.node.save()

        with task_manager.acquire(
                self.context, self.node.uuid, shared=False) as task:
            self.assertRaises(exception.MissingParameterValue,
                              self.driver.validate, task)
            pxe_boot_validate_mock.assert_called_once_with(
                task.driver.boot, task)

    @mock.patch.object(pxe.PXEBoot, 'validate', autospec=True)
    def test_validate_nonglance_image_no_checksum_os_algo(
            self, pxe_boot_validate_mock):
        i_info = self.node.instance_info
        i_info['image_source'] = 'http://image-ref'
        i_info['image_os_hash_value'] = 'az'
        del i_info['image_checksum']
        self.node.instance_info = i_info
        self.node.save()

        with task_manager.acquire(
                self.context, self.node.uuid, shared=False) as task:
            self.assertRaises(exception.MissingParameterValue,
                              self.driver.validate, task)
            pxe_boot_validate_mock.assert_called_once_with(
                task.driver.boot, task)

    @mock.patch.object(pxe.PXEBoot, 'validate', autospec=True)
    def test_validate_nonglance_image_no_os_image_hash(
            self, pxe_boot_validate_mock, autospec=True):
        i_info = self.node.instance_info
        i_info['image_source'] = 'http://image-ref'
        i_info['image_os_hash_algo'] = 'magicalgo'
        self.node.instance_info = i_info
        self.node.save()

        with task_manager.acquire(
                self.context, self.node.uuid, shared=False) as task:
            self.assertRaises(exception.MissingParameterValue,
                              self.driver.validate, task)
            pxe_boot_validate_mock.assert_called_once_with(
                task.driver.boot, task)

    @mock.patch.object(pxe.PXEBoot, 'validate', autospec=True)
    def test_validate_nonglance_image_no_os_algo(
            self, pxe_boot_validate_mock):
        i_info = self.node.instance_info
        i_info['image_source'] = 'http://image-ref'
        i_info['image_os_hash_value'] = 'az'
        self.node.instance_info = i_info
        self.node.save()

        with task_manager.acquire(
                self.context, self.node.uuid, shared=False) as task:
            self.assertRaises(exception.MissingParameterValue,
                              self.driver.validate, task)
            pxe_boot_validate_mock.assert_called_once_with(
                task.driver.boot, task)

    @mock.patch.object(pxe.PXEBoot, 'validate', autospec=True)
    def test_validate_nonglance_image_no_os_checksum(
            self, pxe_boot_validate_mock):
        i_info = self.node.instance_info
        i_info['image_source'] = 'http://image-ref'
        del i_info['image_checksum']
        i_info['image_os_hash_algo'] = 'whacky-algo-1'
        i_info['image_os_hash_value'] = '1234567890'
        self.node.instance_info = i_info
        self.node.save()

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            self.driver.validate(task)
            pxe_boot_validate_mock.assert_called_once_with(
                task.driver.boot, task)

    @mock.patch.object(pxe.PXEBoot, 'validate', autospec=True)
    def test_validate_file_image_no_checksum(
            self, pxe_boot_validate_mock):
        i_info = self.node.instance_info
        i_info['image_source'] = 'file://image-ref'
        del i_info['image_checksum']
        self.node.instance_info = i_info
        self.node.save()

        with task_manager.acquire(
                self.context, self.node.uuid, shared=False) as task:
            self.driver.validate(task)
            pxe_boot_validate_mock.assert_called_once_with(
                task.driver.boot, task)

    @mock.patch.object(agent, 'validate_http_provisioning_configuration',
                       autospec=True)
    @mock.patch.object(pxe.PXEBoot, 'validate', autospec=True)
    def test_validate_invalid_root_device_hints(
            self, pxe_boot_validate_mock, validate_http_mock):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            task.node.properties['root_device'] = {'size': 'not-int'}
            self.assertRaises(exception.InvalidParameterValue,
                              task.driver.deploy.validate, task)
            pxe_boot_validate_mock.assert_called_once_with(
                task.driver.boot, task)
            validate_http_mock.assert_not_called()

    @mock.patch.object(agent, 'validate_http_provisioning_configuration',
                       autospec=True)
    @mock.patch.object(images, 'image_show', autospec=True)
    @mock.patch.object(pxe.PXEBoot, 'validate', autospec=True)
    def test_validate_invalid_root_device_hints_iinfo(
            self, pxe_boot_validate_mock, show_mock, validate_http_mock):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            task.node.properties['root_device'] = {'size': 42}
            task.node.instance_info['root_device'] = {'size': 'not-int'}
            self.assertRaises(exception.InvalidParameterValue,
                              task.driver.deploy.validate, task)
            pxe_boot_validate_mock.assert_called_once_with(
                task.driver.boot, task)
            show_mock.assert_not_called()
            validate_http_mock.assert_not_called()

    @mock.patch.object(agent, 'validate_http_provisioning_configuration',
                       autospec=True)
    @mock.patch.object(pxe.PXEBoot, 'validate', autospec=True)
    def test_validate_invalid_proxies(self, pxe_boot_validate_mock,
                                      validate_http_mock):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            task.node.driver_info.update({
                'image_https_proxy': 'git://spam.ni',
                'image_http_proxy': 'http://spam.ni',
                'image_no_proxy': '1' * 500})
            self.assertRaisesRegex(exception.InvalidParameterValue,
                                   'image_https_proxy.*image_no_proxy',
                                   task.driver.deploy.validate, task)
            pxe_boot_validate_mock.assert_called_once_with(
                task.driver.boot, task)
            validate_http_mock.assert_called_once_with(task.node)

    def test_validate_invalid_image_type(self):
        with task_manager.acquire(
                self.context, self.node['uuid'], shared=False) as task:
            task.node.instance_info['image_source'] = 'http://image-ref'
            task.node.instance_info['image_type'] = 'passport photo'
            self.assertRaisesRegex(exception.InvalidParameterValue,
                                   'passport photo',
                                   self.driver.validate, task)

    @mock.patch.object(pxe.PXEBoot, 'validate', autospec=True)
    @mock.patch.object(deploy_utils, 'check_for_missing_params',
                       autospec=True)
    @mock.patch.object(deploy_utils, 'validate_capabilities', autospec=True)
    @mock.patch.object(noop_storage.NoopStorage, 'should_write_image',
                       autospec=True)
    def test_validate_storage_should_write_image_false(self, mock_write,
                                                       mock_capabilities,
                                                       mock_params,
                                                       mock_pxe_validate):
        mock_write.return_value = False
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:

            self.driver.validate(task)
            mock_capabilities.assert_called_once_with(task.node)
            self.assertFalse(mock_params.called)

    @mock.patch.object(noop_storage.NoopStorage, 'detach_volumes',
                       autospec=True)
    @mock.patch.object(flat_network.FlatNetwork,
                       'remove_provisioning_network',
                       spec_set=True, autospec=True)
    @mock.patch.object(flat_network.FlatNetwork,
                       'unconfigure_tenant_networks',
                       spec_set=True, autospec=True)
    @mock.patch('ironic.conductor.utils.node_power_action', autospec=True)
    def test_tear_down(self, power_mock,
                       unconfigure_tenant_nets_mock,
                       remove_provisioning_net_mock,
                       storage_detach_volumes_mock):
        object_utils.create_test_volume_target(
            self.context, node_id=self.node.id)
        node = self.node
        node.network_interface = 'flat'
        node.save()
        with task_manager.acquire(
                self.context, self.node['uuid'], shared=False) as task:
            driver_return = self.driver.tear_down(task)
            power_mock.assert_called_once_with(task, states.POWER_OFF)
            self.assertEqual(driver_return, states.DELETED)
            unconfigure_tenant_nets_mock.assert_called_once_with(mock.ANY,
                                                                 task)
            remove_provisioning_net_mock.assert_called_once_with(mock.ANY,
                                                                 task)
            storage_detach_volumes_mock.assert_called_once_with(
                task.driver.storage, task)
        # Verify no volumes exist for new task instances.
        with task_manager.acquire(
                self.context, self.node['uuid'], shared=False) as task:
            self.assertEqual(0, len(task.volume_targets))

    @mock.patch('ironic.drivers.modules.agent.check_image_size',
                autospec=True)
    @mock.patch.object(noop_storage.NoopStorage, 'attach_volumes',
                       autospec=True)
    @mock.patch.object(deploy_utils, 'populate_storage_driver_internal_info',
                       autospec=True)
    @mock.patch.object(pxe.PXEBoot, 'prepare_ramdisk', autospec=True)
    @mock.patch.object(deploy_utils, 'build_agent_options', autospec=True)
    @mock.patch.object(deploy_utils, 'build_instance_info_for_deploy',
                       autospec=True)
    @mock.patch.object(flat_network.FlatNetwork, 'add_provisioning_network',
                       spec_set=True, autospec=True)
    @mock.patch.object(flat_network.FlatNetwork,
                       'unconfigure_tenant_networks',
                       spec_set=True, autospec=True)
    @mock.patch.object(flat_network.FlatNetwork, 'validate',
                       spec_set=True, autospec=True)
    def test_prepare(
            self, validate_net_mock,
            unconfigure_tenant_net_mock, add_provisioning_net_mock,
            build_instance_info_mock, build_options_mock,
            pxe_prepare_ramdisk_mock, storage_driver_info_mock,
            storage_attach_volumes_mock, check_image_size_mock):
        node = self.node
        node.network_interface = 'flat'
        node.save()
        with task_manager.acquire(
                self.context, self.node['uuid'], shared=False) as task:
            task.node.provision_state = states.DEPLOYING
            build_instance_info_mock.return_value = {'foo': 'bar'}
            build_options_mock.return_value = {'a': 'b'}
            self.driver.prepare(task)
            storage_driver_info_mock.assert_called_once_with(task)
            validate_net_mock.assert_called_once_with(mock.ANY, task)
            add_provisioning_net_mock.assert_called_once_with(mock.ANY, task)
            unconfigure_tenant_net_mock.assert_called_once_with(mock.ANY, task)
            storage_attach_volumes_mock.assert_called_once_with(
                task.driver.storage, task)
            build_instance_info_mock.assert_called_once_with(task)
            build_options_mock.assert_called_once_with(task.node)
            pxe_prepare_ramdisk_mock.assert_called_once_with(
                task.driver.boot, task, {'a': 'b'})
            check_image_size_mock.assert_called_once_with(task)
        self.node.refresh()
        self.assertEqual('bar', self.node.instance_info['foo'])

    @mock.patch('ironic.drivers.modules.agent.check_image_size',
                autospec=True)
    @mock.patch.object(noop_storage.NoopStorage, 'attach_volumes',
                       autospec=True)
    @mock.patch.object(deploy_utils, 'populate_storage_driver_internal_info',
                       autospec=True)
    @mock.patch.object(pxe.PXEBoot, 'prepare_ramdisk', autospec=True)
    @mock.patch.object(deploy_utils, 'build_agent_options', autospec=True)
    @mock.patch.object(deploy_utils, 'build_instance_info_for_deploy',
                       autospec=True)
    @mock.patch.object(neutron_network.NeutronNetwork,
                       'add_provisioning_network',
                       spec_set=True, autospec=True)
    @mock.patch.object(neutron_network.NeutronNetwork,
                       'unconfigure_tenant_networks',
                       spec_set=True, autospec=True)
    @mock.patch.object(neutron_network.NeutronNetwork, 'validate',
                       spec_set=True, autospec=True)
    def test_prepare_with_neutron_net(
            self, validate_net_mock,
            unconfigure_tenant_net_mock, add_provisioning_net_mock,
            build_instance_info_mock, build_options_mock,
            pxe_prepare_ramdisk_mock, storage_driver_info_mock,
            storage_attach_volumes_mock, check_image_size_mock):
        node = self.node
        node.network_interface = 'neutron'
        node.save()
        with task_manager.acquire(
                self.context, self.node['uuid'], shared=False) as task:
            task.node.provision_state = states.DEPLOYING
            build_instance_info_mock.return_value = {'foo': 'bar'}
            build_options_mock.return_value = {'a': 'b'}
            self.driver.prepare(task)
            storage_driver_info_mock.assert_called_once_with(task)
            validate_net_mock.assert_called_once_with(mock.ANY, task)
            add_provisioning_net_mock.assert_called_once_with(mock.ANY, task)
            unconfigure_tenant_net_mock.assert_called_once_with(mock.ANY, task)
            storage_attach_volumes_mock.assert_called_once_with(
                task.driver.storage, task)
            build_instance_info_mock.assert_called_once_with(task)
            build_options_mock.assert_called_once_with(task.node)
            pxe_prepare_ramdisk_mock.assert_called_once_with(
                task.driver.boot, task, {'a': 'b'})
            check_image_size_mock.assert_called_once_with(task)
        self.node.refresh()
        self.assertEqual('bar', self.node.instance_info['foo'])

    @mock.patch('ironic.drivers.modules.agent.check_image_size',
                autospec=True)
    @mock.patch.object(flat_network.FlatNetwork, 'add_provisioning_network',
                       spec_set=True, autospec=True)
    @mock.patch.object(flat_network.FlatNetwork, 'validate',
                       spec_set=True, autospec=True)
    @mock.patch.object(pxe.PXEBoot, 'prepare_ramdisk', autospec=True)
    @mock.patch.object(deploy_utils, 'build_agent_options', autospec=True)
    @mock.patch.object(deploy_utils, 'build_instance_info_for_deploy',
                       autospec=True)
    def test_prepare_manage_agent_boot_false(
            self, build_instance_info_mock,
            build_options_mock, pxe_prepare_ramdisk_mock,
            validate_net_mock, add_provisioning_net_mock,
            check_image_size_mock):
        self.config(group='agent', manage_agent_boot=False)
        node = self.node
        node.network_interface = 'flat'
        node.save()
        with task_manager.acquire(
                self.context, self.node['uuid'], shared=False) as task:
            task.node.provision_state = states.DEPLOYING
            build_instance_info_mock.return_value = {'foo': 'bar'}

            self.driver.prepare(task)

            validate_net_mock.assert_called_once_with(mock.ANY, task)
            build_instance_info_mock.assert_called_once_with(task)
            add_provisioning_net_mock.assert_called_once_with(mock.ANY, task)
            check_image_size_mock.assert_called_once_with(task)
            self.assertFalse(build_options_mock.called)
            self.assertFalse(pxe_prepare_ramdisk_mock.called)

        self.node.refresh()
        self.assertEqual('bar', self.node.instance_info['foo'])

    @mock.patch.object(pxe.PXEBoot, 'prepare_ramdisk', autospec=True)
    @mock.patch.object(deploy_utils, 'build_agent_options', autospec=True)
    @mock.patch.object(deploy_utils, 'build_instance_info_for_deploy',
                       autospec=True)
    def _test_prepare_rescue_states(
            self, build_instance_info_mock, build_options_mock,
            pxe_prepare_ramdisk_mock, prov_state):
        with task_manager.acquire(
                self.context, self.node['uuid'], shared=False) as task:
            task.node.provision_state = prov_state
            build_options_mock.return_value = {'a': 'b'}
            self.driver.prepare(task)
            self.assertFalse(build_instance_info_mock.called)
            build_options_mock.assert_called_once_with(task.node)
            pxe_prepare_ramdisk_mock.assert_called_once_with(
                task.driver.boot, task, {'a': 'b'})

    def test_prepare_rescue_states(self):
        for state in (states.RESCUING, states.RESCUEWAIT,
                      states.RESCUE, states.RESCUEFAIL):
            self._test_prepare_rescue_states(prov_state=state)

    @mock.patch.object(noop_storage.NoopStorage, 'attach_volumes',
                       autospec=True)
    @mock.patch.object(deploy_utils, 'populate_storage_driver_internal_info',
                       autospec=True)
    @mock.patch.object(flat_network.FlatNetwork, 'add_provisioning_network',
                       spec_set=True, autospec=True)
    @mock.patch.object(pxe.PXEBoot, 'prepare_instance',
                       spec_set=True, autospec=True)
    @mock.patch.object(pxe.PXEBoot, 'prepare_ramdisk',
                       spec_set=True, autospec=True)
    @mock.patch.object(deploy_utils, 'build_agent_options',
                       spec_set=True, autospec=True)
    @mock.patch.object(deploy_utils, 'build_instance_info_for_deploy',
                       spec_set=True, autospec=True)
    def _test_prepare_conductor_takeover(
            self, build_instance_info_mock, build_options_mock,
            pxe_prepare_ramdisk_mock, pxe_prepare_instance_mock,
            add_provisioning_net_mock, storage_driver_info_mock,
            storage_attach_volumes_mock, prov_state):
        with task_manager.acquire(
                self.context, self.node['uuid'], shared=False) as task:
            task.node.provision_state = prov_state

            self.driver.prepare(task)

            self.assertFalse(build_instance_info_mock.called)
            self.assertFalse(build_options_mock.called)
            self.assertFalse(pxe_prepare_ramdisk_mock.called)
            self.assertTrue(pxe_prepare_instance_mock.called)
            self.assertFalse(add_provisioning_net_mock.called)
            self.assertTrue(storage_driver_info_mock.called)
            self.assertFalse(storage_attach_volumes_mock.called)

    def test_prepare_active_and_unrescue_states(self):
        for prov_state in (states.ACTIVE, states.UNRESCUING):
            self._test_prepare_conductor_takeover(
                prov_state=prov_state)

    @mock.patch.object(noop_storage.NoopStorage, 'should_write_image',
                       autospec=True)
    @mock.patch.object(noop_storage.NoopStorage, 'attach_volumes',
                       autospec=True)
    @mock.patch.object(deploy_utils, 'populate_storage_driver_internal_info',
                       autospec=True)
    @mock.patch.object(flat_network.FlatNetwork, 'add_provisioning_network',
                       spec_set=True, autospec=True)
    @mock.patch.object(flat_network.FlatNetwork,
                       'unconfigure_tenant_networks',
                       spec_set=True, autospec=True)
    @mock.patch.object(flat_network.FlatNetwork, 'validate',
                       spec_set=True, autospec=True)
    @mock.patch.object(pxe.PXEBoot, 'prepare_instance', autospec=True)
    @mock.patch.object(pxe.PXEBoot, 'prepare_ramdisk', autospec=True)
    @mock.patch.object(deploy_utils, 'build_agent_options', autospec=True)
    @mock.patch.object(deploy_utils, 'build_instance_info_for_deploy',
                       autospec=True)
    def test_prepare_storage_write_false(
            self, build_instance_info_mock, build_options_mock,
            pxe_prepare_ramdisk_mock, pxe_prepare_instance_mock,
            validate_net_mock, remove_tenant_net_mock,
            add_provisioning_net_mock, storage_driver_info_mock,
            storage_attach_volumes_mock, should_write_image_mock):
        should_write_image_mock.return_value = False
        node = self.node
        node.network_interface = 'flat'
        node.save()
        with task_manager.acquire(
                self.context, self.node['uuid'], shared=False) as task:
            task.node.provision_state = states.DEPLOYING

            self.driver.prepare(task)
            validate_net_mock.assert_called_once_with(mock.ANY, task)
            self.assertFalse(build_instance_info_mock.called)
            self.assertFalse(build_options_mock.called)
            self.assertFalse(pxe_prepare_ramdisk_mock.called)
            self.assertFalse(pxe_prepare_instance_mock.called)
            self.assertFalse(add_provisioning_net_mock.called)
            self.assertTrue(storage_driver_info_mock.called)
            self.assertTrue(storage_attach_volumes_mock.called)
            self.assertEqual(2, should_write_image_mock.call_count)

    @mock.patch.object(pxe.PXEBoot, 'prepare_instance', autospec=True)
    @mock.patch.object(flat_network.FlatNetwork, 'add_provisioning_network',
                       spec_set=True, autospec=True)
    @mock.patch.object(pxe.PXEBoot, 'prepare_ramdisk', autospec=True)
    @mock.patch.object(deploy_utils, 'build_agent_options', autospec=True)
    @mock.patch.object(deploy_utils, 'build_instance_info_for_deploy',
                       autospec=True)
    def test_prepare_adopting(
            self, build_instance_info_mock, build_options_mock,
            pxe_prepare_ramdisk_mock, add_provisioning_net_mock,
            prepare_instance_mock):
        with task_manager.acquire(
                self.context, self.node['uuid'], shared=False) as task:
            task.node.provision_state = states.ADOPTING

            self.driver.prepare(task)

            self.assertFalse(build_instance_info_mock.called)
            self.assertFalse(build_options_mock.called)
            self.assertFalse(pxe_prepare_ramdisk_mock.called)
            self.assertFalse(add_provisioning_net_mock.called)
            self.assertTrue(prepare_instance_mock.called)

    @mock.patch.object(flat_network.FlatNetwork, 'add_provisioning_network',
                       spec_set=True, autospec=True)
    @mock.patch.object(flat_network.FlatNetwork, 'validate',
                       spec_set=True, autospec=True)
    @mock.patch.object(pxe.PXEBoot, 'prepare_ramdisk', autospec=True)
    @mock.patch.object(deploy_utils, 'build_agent_options', autospec=True)
    @mock.patch.object(deploy_utils, 'build_instance_info_for_deploy',
                       autospec=True)
    @mock.patch.object(noop_storage.NoopStorage, 'should_write_image',
                       autospec=True)
    def test_prepare_boot_from_volume(self, mock_write,
                                      build_instance_info_mock,
                                      build_options_mock,
                                      pxe_prepare_ramdisk_mock,
                                      validate_net_mock,
                                      add_provisioning_net_mock):
        mock_write.return_value = False
        node = self.node
        node.network_interface = 'flat'
        node.save()
        with task_manager.acquire(
                self.context, self.node['uuid'], shared=False) as task:
            task.node.provision_state = states.DEPLOYING
            build_instance_info_mock.return_value = {'foo': 'bar'}
            build_options_mock.return_value = {'a': 'b'}

            self.driver.prepare(task)
            validate_net_mock.assert_called_once_with(mock.ANY, task)
            build_instance_info_mock.assert_not_called()
            build_options_mock.assert_not_called()
            pxe_prepare_ramdisk_mock.assert_not_called()

    @mock.patch('ironic.drivers.modules.agent.check_image_size',
                autospec=True)
    @mock.patch('ironic.conductor.utils.is_fast_track', autospec=True)
    @mock.patch.object(noop_storage.NoopStorage, 'attach_volumes',
                       autospec=True)
    @mock.patch.object(deploy_utils, 'populate_storage_driver_internal_info',
                       autospec=True)
    @mock.patch.object(pxe.PXEBoot, 'prepare_ramdisk', autospec=True)
    @mock.patch.object(deploy_utils, 'build_agent_options', autospec=True)
    @mock.patch.object(deploy_utils, 'build_instance_info_for_deploy',
                       autospec=True)
    @mock.patch.object(flat_network.FlatNetwork, 'add_provisioning_network',
                       spec_set=True, autospec=True)
    @mock.patch.object(flat_network.FlatNetwork,
                       'unconfigure_tenant_networks',
                       spec_set=True, autospec=True)
    @mock.patch.object(flat_network.FlatNetwork, 'validate',
                       spec_set=True, autospec=True)
    def test_prepare_fast_track(
            self, validate_net_mock,
            unconfigure_tenant_net_mock, add_provisioning_net_mock,
            build_instance_info_mock, build_options_mock,
            pxe_prepare_ramdisk_mock, storage_driver_info_mock,
            storage_attach_volumes_mock, is_fast_track_mock,
            check_image_size_mock):
        # TODO(TheJulia): We should revisit this test. Smartnic
        # support didn't wire in tightly on testing for power in
        # these tests, and largely fast_track impacts power operations.
        node = self.node
        node.network_interface = 'flat'
        node.save()
        is_fast_track_mock.return_value = True
        with task_manager.acquire(
                self.context, self.node['uuid'], shared=False) as task:
            task.node.provision_state = states.DEPLOYING
            build_options_mock.return_value = {'a': 'b'}
            self.driver.prepare(task)
            storage_driver_info_mock.assert_called_once_with(task)
            validate_net_mock.assert_called_once_with(mock.ANY, task)
            add_provisioning_net_mock.assert_called_once_with(mock.ANY, task)
            unconfigure_tenant_net_mock.assert_called_once_with(mock.ANY, task)
            check_image_size_mock.assert_called_once_with(task)
            self.assertTrue(storage_attach_volumes_mock.called)
            self.assertTrue(build_instance_info_mock.called)
            # TODO(TheJulia): We should likely consider executing the
            # next two methods at some point in order to facilitate
            # continuity. While not explicitly required for this feature
            # to work, reboots as part of deployment would need the ramdisk
            # present and ready.
            self.assertFalse(build_options_mock.called)
            self.assertFalse(pxe_prepare_ramdisk_mock.called)

    @mock.patch.object(agent_base, 'get_steps', autospec=True)
    def test_get_clean_steps(self, mock_get_steps):
        # Test getting clean steps
        mock_steps = [{'priority': 10, 'interface': 'deploy',
                       'step': 'erase_devices'}]
        mock_get_steps.return_value = mock_steps
        with task_manager.acquire(self.context, self.node.uuid) as task:
            steps = self.driver.get_clean_steps(task)
            mock_get_steps.assert_called_once_with(
                task, 'clean', interface='deploy',
                override_priorities={'erase_devices': None,
                                     'erase_devices_metadata': None})
        self.assertEqual(mock_steps, steps)

    @mock.patch.object(agent_base, 'get_steps', autospec=True)
    def test_get_service_steps(self, mock_get_steps):
        # Test getting service steps
        mock_steps = [{'priority': 10, 'interface': 'deploy',
                       'step': 'erase_devices'}]
        mock_get_steps.return_value = mock_steps
        with task_manager.acquire(self.context, self.node.uuid) as task:
            steps = self.driver.get_service_steps(task)
            mock_get_steps.assert_called_once_with(
                task, 'service',
                override_priorities={'erase_devices': None,
                                     'erase_devices_metadata': None})
        self.assertEqual(mock_steps, steps)

    @mock.patch.object(agent_base, 'get_steps', autospec=True)
    def test_get_clean_steps_config_priority(self, mock_get_steps):
        # Test that we can override the priority of get clean steps
        # Use 0 because it is an edge case (false-y) and used in devstack
        # for erase_devices.
        self.config(erase_devices_priority=0, group='deploy')
        self.config(erase_devices_metadata_priority=0, group='deploy')
        mock_steps = [{'priority': 10, 'interface': 'deploy',
                       'step': 'erase_devices'}]
        mock_get_steps.return_value = mock_steps
        with task_manager.acquire(self.context, self.node.uuid) as task:
            self.driver.get_clean_steps(task)
            mock_get_steps.assert_called_once_with(
                task, 'clean', interface='deploy',
                override_priorities={'erase_devices': 0,
                                     'erase_devices_metadata': 0})

    @mock.patch.object(deploy_utils, 'prepare_inband_cleaning', autospec=True)
    def test_prepare_cleaning(self, prepare_inband_cleaning_mock):
        prepare_inband_cleaning_mock.return_value = states.CLEANWAIT
        with task_manager.acquire(self.context, self.node.uuid) as task:
            self.assertEqual(
                states.CLEANWAIT, self.driver.prepare_cleaning(task))
            prepare_inband_cleaning_mock.assert_called_once_with(
                task, manage_boot=True)

    @mock.patch.object(deploy_utils, 'prepare_inband_service', autospec=True)
    def test_prepare_service(self, prepare_inband_service_mock):
        prepare_inband_service_mock.return_value = states.SERVICEWAIT
        with task_manager.acquire(self.context, self.node.uuid) as task:
            self.assertEqual(
                states.SERVICEWAIT, self.driver.prepare_service(task))
            prepare_inband_service_mock.assert_called_once_with(task)

    @mock.patch.object(deploy_utils, 'prepare_inband_cleaning', autospec=True)
    def test_prepare_cleaning_manage_agent_boot_false(
            self, prepare_inband_cleaning_mock):
        prepare_inband_cleaning_mock.return_value = states.CLEANWAIT
        self.config(group='agent', manage_agent_boot=False)
        with task_manager.acquire(self.context, self.node.uuid) as task:
            self.assertEqual(
                states.CLEANWAIT, self.driver.prepare_cleaning(task))
            prepare_inband_cleaning_mock.assert_called_once_with(
                task, manage_boot=False)

    @mock.patch.object(agent.AgentDeploy, 'refresh_steps', autospec=True)
    @mock.patch.object(deploy_utils, 'prepare_inband_cleaning', autospec=True)
    def test_prepare_cleaning_fast_track(self, prepare_inband_cleaning_mock,
                                         refresh_steps_mock):
        prepare_inband_cleaning_mock.return_value = None
        with task_manager.acquire(self.context, self.node.uuid) as task:
            self.assertIsNone(self.driver.prepare_cleaning(task))
            prepare_inband_cleaning_mock.assert_called_once_with(
                task, manage_boot=True)
            refresh_steps_mock.assert_called_once_with(
                self.driver, task, 'clean')

    @mock.patch.object(deploy_utils, 'tear_down_inband_cleaning',
                       autospec=True)
    def test_tear_down_cleaning(self, tear_down_cleaning_mock):
        with task_manager.acquire(self.context, self.node.uuid) as task:
            self.driver.tear_down_cleaning(task)
            tear_down_cleaning_mock.assert_called_once_with(
                task, manage_boot=True)

    @mock.patch.object(deploy_utils, 'tear_down_inband_service',
                       autospec=True)
    def test_tear_down_service(self, tear_down_service_mock):
        with task_manager.acquire(self.context, self.node.uuid) as task:
            self.driver.tear_down_service(task)
            tear_down_service_mock.assert_called_once_with(
                task)

    @mock.patch.object(deploy_utils, 'tear_down_inband_cleaning',
                       autospec=True)
    def test_tear_down_cleaning_manage_agent_boot_false(
            self, tear_down_cleaning_mock):
        self.config(group='agent', manage_agent_boot=False)
        with task_manager.acquire(self.context, self.node.uuid) as task:
            self.driver.tear_down_cleaning(task)
            tear_down_cleaning_mock.assert_called_once_with(
                task, manage_boot=False)

    def _test_write_image(self, additional_driver_info=None,
                          additional_expected_image_info=None):
        self.node.provision_state = states.DEPLOYWAIT
        self.node.target_provision_state = states.ACTIVE
        driver_info = self.node.driver_info
        driver_info.update(additional_driver_info or {})
        self.node.driver_info = driver_info

        step = {'step': 'write_image', 'interface': 'deploy'}
        dii = self.node.driver_internal_info
        dii['agent_cached_deploy_steps'] = {
            'deploy': [step],
        }
        self.node.driver_internal_info = dii
        self.node.save()

        test_temp_url = 'http://image'
        expected_image_info = {
            'urls': [test_temp_url],
            'id': 'fake-image',
            'node_uuid': self.node.uuid,
            'checksum': 'checksum',
            'disk_format': 'qcow2',
            'container_format': 'bare',
            'stream_raw_images': CONF.agent.stream_raw_images,
        }
        expected_image_info.update(additional_expected_image_info or {})

        client_mock = mock.MagicMock(spec_set=['execute_deploy_step'])

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.cached_agent_client = client_mock
            task.driver.deploy.write_image(task)

            step['args'] = {'image_info': expected_image_info,
                            'configdrive': None}
            client_mock.execute_deploy_step.assert_called_once_with(
                step, task.node, mock.ANY)
            self.assertEqual(states.DEPLOYWAIT, task.node.provision_state)
            self.assertEqual(states.ACTIVE,
                             task.node.target_provision_state)

    def test_write_image(self):
        self._test_write_image()

    def test_write_image_with_proxies(self):
        self._test_write_image(
            additional_driver_info={'image_https_proxy': 'https://spam.ni',
                                    'image_http_proxy': 'spam.ni',
                                    'image_no_proxy': '.eggs.com'},
            additional_expected_image_info={
                'proxies': {'https': 'https://spam.ni',
                            'http': 'spam.ni'},
                'no_proxy': '.eggs.com'}
        )

    def test_write_image_basic_auth_success(self):
        cfg.CONF.set_override('image_server_auth_strategy',
                              'http_basic',
                              'deploy')
        cfg.CONF.set_override('image_server_user',
                              'SpongeBob',
                              'deploy')
        cfg.CONF.set_override('image_server_password',
                              'SquarePants',
                              'deploy')
        self._test_write_image(
            additional_expected_image_info={
                'image_server_auth_strategy': 'http_basic',
                'image_server_user': 'SpongeBob',
                'image_server_password': 'SquarePants'
            }
        )

    def test_write_image_basic_auth_success_blocked(self):
        cfg.CONF.set_override('image_server_user',
                              'SpongeBob',
                              'deploy')
        cfg.CONF.set_override('image_server_password',
                              'SquarePants',
                              'deploy')
        self._test_write_image()

    def test_write_image_with_no_proxy_without_proxies(self):
        self._test_write_image(
            additional_driver_info={'image_no_proxy': '.eggs.com'}
        )

    def test_write_image_image_source_is_url(self):
        instance_info = self.node.instance_info
        instance_info['image_source'] = 'http://example.com/woof.img'
        self.node.instance_info = instance_info
        self._test_write_image(
            additional_expected_image_info={
                'id': 'woof.img'
            }
        )

    def test_write_image_partition_image(self):
        self.node.provision_state = states.DEPLOYWAIT
        self.node.target_provision_state = states.ACTIVE
        i_info = self.node.instance_info
        i_info['kernel'] = 'kernel'
        i_info['ramdisk'] = 'ramdisk'
        i_info['root_gb'] = 10
        i_info['swap_mb'] = 10
        i_info['ephemeral_mb'] = 0
        i_info['ephemeral_format'] = 'abc'
        i_info['configdrive'] = 'configdrive'
        i_info['preserve_ephemeral'] = False
        i_info['image_type'] = 'partition'
        i_info['root_mb'] = 10240
        i_info['deploy_boot_mode'] = 'bios'
        i_info['capabilities'] = {"boot_option": "local",
                                  "disk_label": "msdos"}
        self.node.instance_info = i_info
        driver_internal_info = self.node.driver_internal_info
        driver_internal_info['is_whole_disk_image'] = False
        self.node.driver_internal_info = driver_internal_info
        self.node.save()
        test_temp_url = 'http://image'
        expected_image_info = {
            'urls': [test_temp_url],
            'id': 'fake-image',
            'node_uuid': self.node.uuid,
            'checksum': 'checksum',
            'disk_format': 'qcow2',
            'container_format': 'bare',
            'stream_raw_images': True,
            'kernel': 'kernel',
            'ramdisk': 'ramdisk',
            'root_gb': 10,
            'swap_mb': 10,
            'ephemeral_mb': 0,
            'ephemeral_format': 'abc',
            'configdrive': 'configdrive',
            'preserve_ephemeral': False,
            'image_type': 'partition',
            'root_mb': 10240,
            'boot_option': 'local',
            'deploy_boot_mode': 'bios',
            'disk_label': 'msdos'
        }

        client_mock = mock.MagicMock(spec_set=['execute_deploy_step'])

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.cached_agent_client = client_mock
            task.driver.deploy.write_image(task)

            step = {'step': 'write_image', 'interface': 'deploy',
                    'args': {'image_info': expected_image_info,
                             'configdrive': 'configdrive'}}
            client_mock.execute_deploy_step.assert_called_once_with(
                step, task.node, mock.ANY)
            self.assertEqual(states.DEPLOYWAIT, task.node.provision_state)
            self.assertEqual(states.ACTIVE,
                             task.node.target_provision_state)

    @mock.patch.object(manager_utils, 'build_configdrive', autospec=True)
    def test_write_image_render_configdrive(self, mock_build_configdrive):
        self.node.provision_state = states.DEPLOYWAIT
        self.node.target_provision_state = states.ACTIVE
        i_info = self.node.instance_info
        i_info['kernel'] = 'kernel'
        i_info['ramdisk'] = 'ramdisk'
        i_info['root_gb'] = 10
        i_info['swap_mb'] = 10
        i_info['ephemeral_mb'] = 0
        i_info['ephemeral_format'] = 'abc'
        i_info['configdrive'] = {'meta_data': {}}
        i_info['preserve_ephemeral'] = False
        i_info['image_type'] = 'partition'
        i_info['root_mb'] = 10240
        i_info['deploy_boot_mode'] = 'bios'
        i_info['capabilities'] = {"boot_option": "local",
                                  "disk_label": "msdos"}
        self.node.instance_info = i_info
        driver_internal_info = self.node.driver_internal_info
        driver_internal_info['is_whole_disk_image'] = False
        self.node.driver_internal_info = driver_internal_info
        self.node.save()
        test_temp_url = 'http://image'
        expected_image_info = {
            'urls': [test_temp_url],
            'id': 'fake-image',
            'node_uuid': self.node.uuid,
            'checksum': 'checksum',
            'disk_format': 'qcow2',
            'container_format': 'bare',
            'stream_raw_images': True,
            'kernel': 'kernel',
            'ramdisk': 'ramdisk',
            'root_gb': 10,
            'swap_mb': 10,
            'ephemeral_mb': 0,
            'ephemeral_format': 'abc',
            'configdrive': 'configdrive',
            'preserve_ephemeral': False,
            'image_type': 'partition',
            'root_mb': 10240,
            'boot_option': 'local',
            'deploy_boot_mode': 'bios',
            'disk_label': 'msdos'
        }

        mock_build_configdrive.return_value = 'configdrive'

        client_mock = mock.MagicMock(spec_set=['execute_deploy_step'])

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.cached_agent_client = client_mock
            task.driver.deploy.write_image(task)

            step = {'step': 'write_image', 'interface': 'deploy',
                    'args': {'image_info': expected_image_info,
                             'configdrive': 'configdrive'}}
            client_mock.execute_deploy_step.assert_called_once_with(
                step, task.node, mock.ANY)
            self.assertEqual(states.DEPLOYWAIT, task.node.provision_state)
            self.assertEqual(states.ACTIVE,
                             task.node.target_provision_state)
            mock_build_configdrive.assert_called_once_with(
                task.node, {'meta_data': {}})

    @mock.patch.object(deploy_utils, 'destroy_http_instance_images',
                       autospec=True)
    @mock.patch.object(agent.LOG, 'warning', spec_set=True, autospec=True)
    @mock.patch.object(agent_client.AgentClient, 'get_partition_uuids',
                       autospec=True)
    @mock.patch.object(agent.AgentDeploy, 'prepare_instance_to_boot',
                       autospec=True)
    def test_prepare_instance_boot(self, prepare_instance_mock,
                                   uuid_mock, log_mock, destroy_image_mock):
        self.config(manage_agent_boot=True, group='agent')
        self.config(image_download_source='http', group='agent')
        uuid_mock.return_value = {}
        self.node.provision_state = states.DEPLOYING
        self.node.target_provision_state = states.ACTIVE
        self.node.save()
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.node.driver_internal_info['is_whole_disk_image'] = True
            task.driver.deploy.prepare_instance_boot(task)
            uuid_mock.assert_called_once_with(mock.ANY, task.node)
            self.assertNotIn('root_uuid_or_disk_id',
                             task.node.driver_internal_info)
            self.assertFalse(log_mock.called)
            prepare_instance_mock.assert_called_once_with(mock.ANY, task,
                                                          None, None, None)
            self.assertEqual(states.DEPLOYING, task.node.provision_state)
            self.assertEqual(states.ACTIVE, task.node.target_provision_state)
            destroy_image_mock.assert_called_once_with(task.node)

    @mock.patch.object(deploy_utils, 'destroy_images', autospec=True)
    @mock.patch.object(agent.LOG, 'warning', spec_set=True, autospec=True)
    @mock.patch.object(manager_utils, 'node_set_boot_device', autospec=True)
    @mock.patch.object(agent_client.AgentClient, 'get_partition_uuids',
                       autospec=True)
    @mock.patch.object(agent.AgentDeploy, 'prepare_instance_to_boot',
                       autospec=True)
    def test_prepare_instance_boot_no_manage_agent_boot(
            self, prepare_instance_mock, uuid_mock,
            bootdev_mock, log_mock, destroy_image_mock):
        self.config(manage_agent_boot=False, group='agent')
        uuid_mock.return_value = {}
        self.node.provision_state = states.DEPLOYING
        self.node.target_provision_state = states.ACTIVE
        self.node.save()
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.node.driver_internal_info['is_whole_disk_image'] = True
            task.driver.deploy.prepare_instance_boot(task)
            uuid_mock.assert_called_once_with(mock.ANY, task.node)
            self.assertNotIn('root_uuid_or_disk_id',
                             task.node.driver_internal_info)
            self.assertFalse(log_mock.called)
            self.assertFalse(prepare_instance_mock.called)
            bootdev_mock.assert_called_once_with(task, 'disk', persistent=True)
            self.assertEqual(states.DEPLOYING, task.node.provision_state)
            self.assertEqual(states.ACTIVE, task.node.target_provision_state)

    @mock.patch.object(deploy_utils, 'destroy_images', autospec=True)
    @mock.patch.object(agent.LOG, 'warning', spec_set=True, autospec=True)
    @mock.patch.object(boot_mode_utils, 'get_boot_mode_for_deploy',
                       autospec=True)
    @mock.patch.object(agent_client.AgentClient, 'get_partition_uuids',
                       autospec=True)
    @mock.patch.object(agent.AgentDeploy, 'prepare_instance_to_boot',
                       autospec=True)
    def test_prepare_instance_boot_partition_image(self, prepare_instance_mock,
                                                   uuid_mock, boot_mode_mock,
                                                   log_mock,
                                                   destroy_image_mock):
        uuid_mock.return_value = {
            'command_result': {'root uuid': 'root_uuid'}
        }
        self.node.provision_state = states.DEPLOYING
        self.node.target_provision_state = states.ACTIVE
        self.node.save()
        boot_mode_mock.return_value = 'bios'
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            driver_internal_info = task.node.driver_internal_info
            driver_internal_info['is_whole_disk_image'] = False
            task.node.driver_internal_info = driver_internal_info
            task.driver.deploy.prepare_instance_boot(task)
            uuid_mock.assert_called_once_with(mock.ANY, task.node)
            driver_int_info = task.node.driver_internal_info
            self.assertEqual('root_uuid',
                             driver_int_info['root_uuid_or_disk_id']),
            boot_mode_mock.assert_called_once_with(task.node)
            self.assertFalse(log_mock.called)
            prepare_instance_mock.assert_called_once_with(mock.ANY,
                                                          task,
                                                          'root_uuid',
                                                          None, None)
            self.assertEqual(states.DEPLOYING, task.node.provision_state)
            self.assertEqual(states.ACTIVE, task.node.target_provision_state)

    @mock.patch.object(deploy_utils, 'destroy_images', autospec=True)
    @mock.patch.object(agent.LOG, 'warning', spec_set=True, autospec=True)
    @mock.patch.object(boot_mode_utils, 'get_boot_mode_for_deploy',
                       autospec=True)
    @mock.patch.object(agent_client.AgentClient, 'get_partition_uuids',
                       autospec=True)
    @mock.patch.object(agent.AgentDeploy, 'prepare_instance_to_boot',
                       autospec=True)
    def test_prepare_instance_boot_partition_localboot_ppc64(
            self, prepare_instance_mock,
            uuid_mock, boot_mode_mock, log_mock, destroy_image_mock):
        uuid_mock.return_value = {
            'command_result': {
                'root uuid': 'root_uuid',
                'PReP Boot partition uuid': 'prep_boot_part_uuid',
            }
        }
        self.node.provision_state = states.DEPLOYING
        self.node.target_provision_state = states.ACTIVE
        self.node.save()

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            driver_internal_info = task.node.driver_internal_info
            driver_internal_info['is_whole_disk_image'] = False
            task.node.driver_internal_info = driver_internal_info
            boot_option = {'capabilities': '{"boot_option": "local"}'}
            task.node.instance_info = boot_option
            properties = task.node.properties
            properties.update(cpu_arch='ppc64le')
            task.node.properties = properties
            boot_mode_mock.return_value = 'bios'
            task.driver.deploy.prepare_instance_boot(task)

            driver_int_info = task.node.driver_internal_info
            self.assertEqual('root_uuid',
                             driver_int_info['root_uuid_or_disk_id']),
            uuid_mock.assert_called_once_with(mock.ANY, task.node)
            boot_mode_mock.assert_called_once_with(task.node)
            self.assertFalse(log_mock.called)
            prepare_instance_mock.assert_called_once_with(
                mock.ANY, task, 'root_uuid', None, 'prep_boot_part_uuid')
            self.assertEqual(states.DEPLOYING, task.node.provision_state)
            self.assertEqual(states.ACTIVE, task.node.target_provision_state)

    @mock.patch.object(deploy_utils, 'destroy_images', autospec=True)
    @mock.patch.object(agent.LOG, 'warning', spec_set=True, autospec=True)
    @mock.patch.object(boot_mode_utils, 'get_boot_mode_for_deploy',
                       autospec=True)
    @mock.patch.object(agent_client.AgentClient, 'get_partition_uuids',
                       autospec=True)
    @mock.patch.object(agent.AgentDeploy, 'prepare_instance_to_boot',
                       autospec=True)
    def test_prepare_instance_boot_localboot(self, prepare_instance_mock,
                                             uuid_mock, boot_mode_mock,
                                             log_mock, destroy_image_mock):
        uuid_mock.return_value = {
            'command_result': {
                'root uuid': 'root_uuid',
                'efi system partition uuid': 'efi_uuid',
            }
        }
        self.node.provision_state = states.DEPLOYING
        self.node.target_provision_state = states.ACTIVE
        self.node.save()

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            driver_internal_info = task.node.driver_internal_info
            driver_internal_info['is_whole_disk_image'] = False
            task.node.driver_internal_info = driver_internal_info
            boot_option = {'capabilities': '{"boot_option": "local"}'}
            task.node.instance_info = boot_option
            boot_mode_mock.return_value = 'uefi'
            task.driver.deploy.prepare_instance_boot(task)

            driver_int_info = task.node.driver_internal_info
            self.assertEqual('root_uuid',
                             driver_int_info['root_uuid_or_disk_id']),
            uuid_mock.assert_called_once_with(mock.ANY, task.node)
            boot_mode_mock.assert_called_once_with(task.node)
            self.assertFalse(log_mock.called)
            prepare_instance_mock.assert_called_once_with(
                mock.ANY, task, 'root_uuid', 'efi_uuid', None)
            self.assertEqual(states.DEPLOYING, task.node.provision_state)
            self.assertEqual(states.ACTIVE, task.node.target_provision_state)

    @mock.patch.object(pxe.PXEBoot, 'prepare_instance', autospec=True)
    @mock.patch.object(noop_storage.NoopStorage, 'should_write_image',
                       autospec=True)
    def test_prepare_instance_boot_storage_should_write_image_with_smartnic(
            self, mock_write, mock_pxe_instance):
        mock_write.return_value = False
        self.node.provision_state = states.DEPLOYING
        self.node.deploy_step = {
            'step': 'deploy', 'priority': 50, 'interface': 'deploy'}
        self.node.save()
        with task_manager.acquire(
                self.context, self.node['uuid'], shared=False) as task:
            driver_return = self.driver.prepare_instance_boot(task)
            self.assertIsNone(driver_return)
            self.assertTrue(mock_pxe_instance.called)

    @mock.patch('ironic.drivers.modules.agent.check_image_size',
                autospec=True)
    @mock.patch.object(manager_utils, 'restore_power_state_if_needed',
                       autospec=True)
    @mock.patch.object(manager_utils, 'power_on_node_if_needed',
                       autospec=True)
    @mock.patch.object(noop_storage.NoopStorage, 'attach_volumes',
                       autospec=True)
    @mock.patch.object(deploy_utils, 'populate_storage_driver_internal_info',
                       autospec=True)
    @mock.patch.object(pxe.PXEBoot, 'prepare_ramdisk', autospec=True)
    @mock.patch.object(deploy_utils, 'build_agent_options', autospec=True)
    @mock.patch.object(deploy_utils, 'build_instance_info_for_deploy',
                       autospec=True)
    @mock.patch.object(flat_network.FlatNetwork,
                       'add_provisioning_network',
                       spec_set=True, autospec=True)
    @mock.patch.object(flat_network.FlatNetwork,
                       'unconfigure_tenant_networks',
                       spec_set=True, autospec=True)
    @mock.patch.object(flat_network.FlatNetwork, 'validate',
                       spec_set=True, autospec=True)
    def test_prepare_with_smartnic_port(
            self, validate_net_mock,
            unconfigure_tenant_net_mock, add_provisioning_net_mock,
            build_instance_info_mock, build_options_mock,
            pxe_prepare_ramdisk_mock, storage_driver_info_mock,
            storage_attach_volumes_mock, power_on_node_if_needed_mock,
            restore_power_state_mock, check_image_size_mock):
        node = self.node
        node.network_interface = 'flat'
        node.save()
        add_provisioning_net_mock.return_value = None
        with task_manager.acquire(
                self.context, self.node['uuid'], shared=False) as task:
            task.node.provision_state = states.DEPLOYING
            build_instance_info_mock.return_value = {'foo': 'bar'}
            build_options_mock.return_value = {'a': 'b'}
            power_on_node_if_needed_mock.return_value = states.POWER_OFF
            self.driver.prepare(task)
            storage_driver_info_mock.assert_called_once_with(task)
            validate_net_mock.assert_called_once_with(mock.ANY, task)
            add_provisioning_net_mock.assert_called_once_with(mock.ANY, task)
            unconfigure_tenant_net_mock.assert_called_once_with(mock.ANY, task)
            storage_attach_volumes_mock.assert_called_once_with(
                task.driver.storage, task)
            build_instance_info_mock.assert_called_once_with(task)
            build_options_mock.assert_called_once_with(task.node)
            pxe_prepare_ramdisk_mock.assert_called_once_with(
                task.driver.boot, task, {'a': 'b'})
            power_on_node_if_needed_mock.assert_called_once_with(task)
            restore_power_state_mock.assert_called_once_with(
                task, states.POWER_OFF)
            check_image_size_mock.assert_called_once_with(task)
        self.node.refresh()
        self.assertEqual('bar', self.node.instance_info['foo'])

    @mock.patch.object(manager_utils, 'restore_power_state_if_needed',
                       autospec=True)
    @mock.patch.object(manager_utils, 'power_on_node_if_needed',
                       autospec=True)
    @mock.patch.object(noop_storage.NoopStorage, 'detach_volumes',
                       autospec=True)
    @mock.patch.object(flat_network.FlatNetwork,
                       'remove_provisioning_network',
                       spec_set=True, autospec=True)
    @mock.patch.object(flat_network.FlatNetwork,
                       'unconfigure_tenant_networks',
                       spec_set=True, autospec=True)
    @mock.patch('ironic.conductor.utils.node_power_action', autospec=True)
    def test_tear_down_with_smartnic_port(
            self, power_mock, unconfigure_tenant_nets_mock,
            remove_provisioning_net_mock, storage_detach_volumes_mock,
            power_on_node_if_needed_mock, restore_power_state_mock):
        object_utils.create_test_volume_target(
            self.context, node_id=self.node.id)
        node = self.node
        node.network_interface = 'flat'
        node.save()
        with task_manager.acquire(
                self.context, self.node['uuid'], shared=False) as task:
            power_on_node_if_needed_mock.return_value = states.POWER_OFF
            driver_return = self.driver.tear_down(task)
            power_mock.assert_called_once_with(task, states.POWER_OFF)
            self.assertEqual(driver_return, states.DELETED)
            unconfigure_tenant_nets_mock.assert_called_once_with(mock.ANY,
                                                                 task)
            remove_provisioning_net_mock.assert_called_once_with(mock.ANY,
                                                                 task)
            storage_detach_volumes_mock.assert_called_once_with(
                task.driver.storage, task)
            power_on_node_if_needed_mock.assert_called_once_with(task)
            restore_power_state_mock.assert_called_once_with(
                task, states.POWER_OFF)
        # Verify no volumes exist for new task instances.
        with task_manager.acquire(
                self.context, self.node['uuid'], shared=False) as task:
            self.assertEqual(0, len(task.volume_targets))


class AgentRAIDTestCase(db_base.DbTestCase):

    def setUp(self):
        super(AgentRAIDTestCase, self).setUp()
        self.config(enabled_raid_interfaces=['fake', 'agent', 'no-raid'])
        self.target_raid_config = {
            "logical_disks": [
                {'size_gb': 200, 'raid_level': "0", 'is_root_volume': True},
                {'size_gb': 200, 'raid_level': "5"}
            ]}
        self.clean_step = {'step': 'create_configuration',
                           'interface': 'raid'}
        n = {
            'boot_interface': 'pxe',
            'deploy_interface': 'direct',
            'raid_interface': 'agent',
            'instance_info': INSTANCE_INFO,
            'driver_info': DRIVER_INFO,
            'driver_internal_info': DRIVER_INTERNAL_INFO,
            'target_raid_config': self.target_raid_config,
            'clean_step': self.clean_step,
        }
        self.node = object_utils.create_test_node(self.context, **n)

    @mock.patch.object(agent_base, 'get_steps', autospec=True)
    def test_get_clean_steps(self, get_steps_mock):
        get_steps_mock.return_value = [
            {'step': 'create_configuration', 'interface': 'raid',
             'priority': 1},
            {'step': 'delete_configuration', 'interface': 'raid',
             'priority': 2}]

        with task_manager.acquire(self.context, self.node.uuid) as task:
            ret = task.driver.raid.get_clean_steps(task)

        self.assertEqual(1, ret[0]['priority'])
        self.assertEqual(2, ret[1]['priority'])

    @mock.patch.object(agent_base, 'get_steps', autospec=True)
    def test_get_clean_steps_config_priority(self, get_steps_mock):
        # Test that we can override the priority of get clean steps
        # Use 0 because it is an edge case (false-y) and used in devstack
        # for erase_devices.
        self.config(create_configuration_priority=50, group='deploy')
        self.config(delete_configuration_priority=40, group='deploy')
        with task_manager.acquire(self.context, self.node.uuid) as task:
            task.driver.raid.get_clean_steps(task)
            get_steps_mock.assert_called_once_with(
                task, 'clean', interface='raid',
                override_priorities={'create_configuration': 50,
                                     'delete_configuration': 40})

    @mock.patch.object(agent_base, 'get_steps', autospec=True)
    def test_get_deploy_steps(self, get_steps_mock):
        get_steps_mock.return_value = [
            {'step': 'apply_configuration', 'interface': 'raid',
             'priority': 0},
        ]

        with task_manager.acquire(self.context, self.node.uuid) as task:
            ret = task.driver.raid.get_deploy_steps(task)

        self.assertEqual('apply_configuration', ret[0]['step'])

    @mock.patch.object(agent_base, 'execute_step', autospec=True)
    def test_apply_configuration(self, execute_mock):
        deploy_step = {
            'interface': 'raid',
            'step': 'apply_configuration',
            'args': {
                'raid_config': self.target_raid_config,
                'delete_existing': True
            },
            'priority': 82
        }
        with task_manager.acquire(self.context, self.node.uuid) as task:
            execute_mock.return_value = states.DEPLOYWAIT
            task.node.deploy_step = deploy_step
            return_value = task.driver.raid.apply_configuration(
                task, self.target_raid_config, delete_existing=True)
            self.assertEqual(states.DEPLOYWAIT, return_value)
            execute_mock.assert_called_once_with(task, deploy_step, 'deploy')

    @mock.patch.object(raid, 'filter_target_raid_config', autospec=True)
    @mock.patch.object(agent_base, 'execute_step', autospec=True)
    def test_create_configuration(self, execute_mock,
                                  filter_target_raid_config_mock):
        with task_manager.acquire(self.context, self.node.uuid) as task:
            execute_mock.return_value = states.CLEANWAIT
            filter_target_raid_config_mock.return_value = (
                self.target_raid_config)
            return_value = task.driver.raid.create_configuration(task)

            self.assertEqual(states.CLEANWAIT, return_value)
            self.assertEqual(
                self.target_raid_config,
                task.node.driver_internal_info['target_raid_config'])
            execute_mock.assert_called_once_with(task, self.clean_step,
                                                 'clean')

    @mock.patch.object(raid, 'filter_target_raid_config', autospec=True)
    @mock.patch.object(agent_base, 'execute_step', autospec=True)
    def test_create_configuration_skip_root(self, execute_mock,
                                            filter_target_raid_config_mock):
        with task_manager.acquire(self.context, self.node.uuid) as task:
            execute_mock.return_value = states.CLEANWAIT
            exp_target_raid_config = {
                "logical_disks": [
                    {'size_gb': 200, 'raid_level': 5}
                ]}
            filter_target_raid_config_mock.return_value = (
                exp_target_raid_config)
            return_value = task.driver.raid.create_configuration(
                task, create_root_volume=False)
            self.assertEqual(states.CLEANWAIT, return_value)
            execute_mock.assert_called_once_with(task, self.clean_step,
                                                 'clean')
            self.assertEqual(
                exp_target_raid_config,
                task.node.driver_internal_info['target_raid_config'])

    @mock.patch.object(raid, 'filter_target_raid_config', autospec=True)
    @mock.patch.object(agent_base, 'execute_step', autospec=True)
    def test_create_configuration_skip_nonroot(self, execute_mock,
                                               filter_target_raid_config_mock):
        with task_manager.acquire(self.context, self.node.uuid) as task:
            execute_mock.return_value = states.CLEANWAIT
            exp_target_raid_config = {
                "logical_disks": [
                    {'size_gb': 200, 'raid_level': 0, 'is_root_volume': True},
                ]}
            filter_target_raid_config_mock.return_value = (
                exp_target_raid_config)
            return_value = task.driver.raid.create_configuration(
                task, create_nonroot_volumes=False)
            self.assertEqual(states.CLEANWAIT, return_value)
            execute_mock.assert_called_once_with(task, self.clean_step,
                                                 'clean')
            self.assertEqual(
                exp_target_raid_config,
                task.node.driver_internal_info['target_raid_config'])

    @mock.patch.object(raid, 'filter_target_raid_config', autospec=True)
    @mock.patch.object(agent_base, 'execute_step', autospec=True)
    def test_create_configuration_no_target_raid_config_after_skipping(
            self, execute_mock, filter_target_raid_config_mock):
        with task_manager.acquire(self.context, self.node.uuid) as task:
            msg = "Node %s has no target RAID configuration" % self.node.uuid
            filter_target_raid_config_mock.side_effect = (
                exception.MissingParameterValue(msg))
            self.assertRaises(
                exception.MissingParameterValue,
                task.driver.raid.create_configuration,
                task, create_root_volume=False,
                create_nonroot_volumes=False)
            self.assertFalse(execute_mock.called)

    @mock.patch.object(raid, 'filter_target_raid_config', autospec=True)
    @mock.patch.object(agent_base, 'execute_step', autospec=True)
    def test_create_configuration_empty_target_raid_config(
            self, execute_mock, filter_target_raid_config_mock):
        execute_mock.return_value = states.CLEANING
        self.node.target_raid_config = {}
        self.node.save()
        with task_manager.acquire(self.context, self.node.uuid) as task:
            msg = "Node %s has no target RAID configuration" % self.node.uuid
            filter_target_raid_config_mock.side_effect = (
                exception.MissingParameterValue(msg))
            self.assertRaises(exception.MissingParameterValue,
                              task.driver.raid.create_configuration,
                              task)
            self.assertFalse(execute_mock.called)

    @mock.patch.object(raid, 'update_raid_info', autospec=True)
    def test__create_configuration_final(
            self, update_raid_info_mock):
        command = {'command_result': {'clean_result': 'foo'}}
        with task_manager.acquire(self.context, self.node.uuid) as task:
            raid_mgmt = agent.AgentRAID
            raid_mgmt._create_configuration_final(task, command)
            update_raid_info_mock.assert_called_once_with(task.node, 'foo')

    @mock.patch.object(raid, 'update_raid_info', autospec=True)
    def _test__create_configuration_final_registered(
            self, update_raid_info_mock, step_type='clean'):
        step = {'interface': 'raid'}
        if step_type == 'clean':
            step['step'] = 'create_configuration'
            self.node.clean_step = step
            state = states.CLEANWAIT
            command = {'command_result': {'clean_result': 'foo'}}
            create_hook = agent_base._get_post_step_hook(self.node, 'clean')
        else:
            step['step'] = 'apply_configuration'
            self.node.deploy_step = step
            command = {'command_result': {'deploy_result': 'foo'}}
            state = states.DEPLOYWAIT
            create_hook = agent_base._get_post_step_hook(self.node, 'deploy')

        with task_manager.acquire(self.context, self.node.uuid) as task:
            task.node.provision_state = state
            create_hook(task, command)
            update_raid_info_mock.assert_called_once_with(task.node, 'foo')

    def test__create_configuration_final_registered_clean(self):
        self._test__create_configuration_final_registered(step_type='clean')

    def test__create_configuration_final_registered_deploy(self):
        self._test__create_configuration_final_registered(step_type='deploy')

    @mock.patch.object(raid, 'update_raid_info', autospec=True)
    def test__create_configuration_final_bad_command_result(
            self, update_raid_info_mock):
        command = {}
        with task_manager.acquire(self.context, self.node.uuid) as task:
            raid_mgmt = agent.AgentRAID
            self.assertRaises(exception.IronicException,
                              raid_mgmt._create_configuration_final,
                              task, command)
            self.assertFalse(update_raid_info_mock.called)

    @mock.patch.object(raid, 'update_raid_info', autospec=True)
    def test__create_configuration_final_bad_command_result2(
            self, update_raid_info_mock):
        command = {'command_result': {'deploy_result': None}}
        with task_manager.acquire(self.context, self.node.uuid) as task:
            raid_mgmt = agent.AgentRAID
            self.assertRaises(exception.IronicException,
                              raid_mgmt._create_configuration_final,
                              task, command)
            self.assertFalse(update_raid_info_mock.called)

    @mock.patch.object(agent_base, 'execute_step', autospec=True)
    def test_delete_configuration(self, execute_mock):
        execute_mock.return_value = states.CLEANING
        with task_manager.acquire(self.context, self.node.uuid) as task:
            return_value = task.driver.raid.delete_configuration(task)

            execute_mock.assert_called_once_with(task, self.clean_step,
                                                 'clean')
            self.assertEqual(states.CLEANING, return_value)

    def test__delete_configuration_final(self):
        command = {'command_result': {'clean_result': 'foo'}}
        with task_manager.acquire(self.context, self.node.uuid) as task:
            task.node.raid_config = {'foo': 'bar'}
            task.node.properties = {'root_device': {'wwn': 'fake wwn'}}
            raid_mgmt = agent.AgentRAID
            raid_mgmt._delete_configuration_final(task, command)

        self.node.refresh()
        self.assertEqual({}, self.node.raid_config)
        self.assertEqual({}, self.node.properties)

    def test__delete_configuration_final_registered(
            self):
        self.node.clean_step = {'interface': 'raid',
                                'step': 'delete_configuration'}
        self.node.raid_config = {'foo': 'bar'}
        command = {'command_result': {'clean_result': 'foo'}}
        delete_hook = agent_base._get_post_step_hook(self.node, 'clean')
        with task_manager.acquire(self.context, self.node.uuid) as task:
            delete_hook(task, command)

        self.node.refresh()
        self.assertEqual({}, self.node.raid_config)


class AgentRescueTestCase(db_base.DbTestCase):

    def setUp(self):
        super(AgentRescueTestCase, self).setUp()
        for iface in drivers_base.ALL_INTERFACES:
            impl = 'fake'
            if iface == 'network':
                impl = 'flat'
            if iface == 'rescue':
                impl = 'agent'
            config_kwarg = {'enabled_%s_interfaces' % iface: [impl],
                            'default_%s_interface' % iface: impl}
            self.config(**config_kwarg)
        self.config(enabled_hardware_types=['fake-hardware'])
        instance_info = INSTANCE_INFO
        instance_info.update({'rescue_password': 'password',
                              'hashed_rescue_password': '1234'})
        driver_info = DRIVER_INFO
        driver_info.update({'rescue_ramdisk': 'my_ramdisk',
                            'rescue_kernel': 'my_kernel'})
        n = {
            'instance_info': instance_info,
            'driver_info': driver_info,
            'driver_internal_info': DRIVER_INTERNAL_INFO,
        }
        self.node = object_utils.create_test_node(self.context, **n)

    @mock.patch.object(flat_network.FlatNetwork, 'add_rescuing_network',
                       spec_set=True, autospec=True)
    @mock.patch.object(flat_network.FlatNetwork, 'unconfigure_tenant_networks',
                       spec_set=True, autospec=True)
    @mock.patch.object(fake.FakeBoot, 'prepare_ramdisk', autospec=True)
    @mock.patch.object(fake.FakeBoot, 'clean_up_instance', autospec=True)
    @mock.patch.object(deploy_utils, 'build_agent_options', autospec=True)
    @mock.patch.object(manager_utils, 'node_power_action', autospec=True)
    def test_agent_rescue(self, mock_node_power_action, mock_build_agent_opts,
                          mock_clean_up_instance, mock_prepare_ramdisk,
                          mock_unconf_tenant_net, mock_add_rescue_net):
        self.config(manage_agent_boot=True, group='agent')
        mock_build_agent_opts.return_value = {'ipa-api-url': 'fake-api'}
        with task_manager.acquire(self.context, self.node.uuid) as task:
            result = task.driver.rescue.rescue(task)
            mock_node_power_action.assert_has_calls(
                [mock.call(task, states.POWER_OFF),
                 mock.call(task, states.POWER_ON)])
            mock_clean_up_instance.assert_called_once_with(mock.ANY, task)
            mock_unconf_tenant_net.assert_called_once_with(mock.ANY, task)
            mock_add_rescue_net.assert_called_once_with(mock.ANY, task)
            mock_build_agent_opts.assert_called_once_with(task.node)
            mock_prepare_ramdisk.assert_called_once_with(
                mock.ANY, task, {'ipa-api-url': 'fake-api'})
            self.assertEqual(states.RESCUEWAIT, result)

    @mock.patch.object(flat_network.FlatNetwork, 'add_rescuing_network',
                       spec_set=True, autospec=True)
    @mock.patch.object(flat_network.FlatNetwork, 'unconfigure_tenant_networks',
                       spec_set=True, autospec=True)
    @mock.patch.object(fake.FakeBoot, 'prepare_ramdisk', autospec=True)
    @mock.patch.object(fake.FakeBoot, 'clean_up_instance', autospec=True)
    @mock.patch.object(deploy_utils, 'build_agent_options', autospec=True)
    @mock.patch.object(manager_utils, 'node_power_action', autospec=True)
    def test_agent_rescue_no_manage_agent_boot(self, mock_node_power_action,
                                               mock_build_agent_opts,
                                               mock_clean_up_instance,
                                               mock_prepare_ramdisk,
                                               mock_unconf_tenant_net,
                                               mock_add_rescue_net):
        self.config(manage_agent_boot=False, group='agent')
        with task_manager.acquire(self.context, self.node.uuid) as task:
            result = task.driver.rescue.rescue(task)
            mock_node_power_action.assert_has_calls(
                [mock.call(task, states.POWER_OFF),
                 mock.call(task, states.POWER_ON)])
            mock_clean_up_instance.assert_called_once_with(mock.ANY, task)
            mock_unconf_tenant_net.assert_called_once_with(mock.ANY, task)
            mock_add_rescue_net.assert_called_once_with(mock.ANY, task)
            self.assertFalse(mock_build_agent_opts.called)
            self.assertFalse(mock_prepare_ramdisk.called)
            self.assertEqual(states.RESCUEWAIT, result)

    @mock.patch.object(flat_network.FlatNetwork, 'remove_rescuing_network',
                       spec_set=True, autospec=True)
    @mock.patch.object(flat_network.FlatNetwork, 'configure_tenant_networks',
                       spec_set=True, autospec=True)
    @mock.patch.object(fake.FakeBoot, 'prepare_instance', autospec=True)
    @mock.patch.object(fake.FakeBoot, 'clean_up_ramdisk', autospec=True)
    @mock.patch.object(manager_utils, 'node_power_action', autospec=True)
    def test_agent_unrescue(self, mock_node_power_action, mock_clean_ramdisk,
                            mock_prepare_instance, mock_conf_tenant_net,
                            mock_remove_rescue_net):
        """Test unrescue in case where boot driver prepares instance reboot."""
        self.config(manage_agent_boot=True, group='agent')
        with task_manager.acquire(self.context, self.node.uuid) as task:
            result = task.driver.rescue.unrescue(task)
            mock_node_power_action.assert_has_calls(
                [mock.call(task, states.POWER_OFF),
                 mock.call(task, states.POWER_ON)])
            mock_clean_ramdisk.assert_called_once_with(
                mock.ANY, task)
            mock_remove_rescue_net.assert_called_once_with(mock.ANY, task)
            mock_conf_tenant_net.assert_called_once_with(mock.ANY, task)
            mock_prepare_instance.assert_called_once_with(mock.ANY, task)
            self.assertEqual(states.ACTIVE, result)

    @mock.patch.object(flat_network.FlatNetwork, 'remove_rescuing_network',
                       spec_set=True, autospec=True)
    @mock.patch.object(flat_network.FlatNetwork, 'configure_tenant_networks',
                       spec_set=True, autospec=True)
    @mock.patch.object(fake.FakeBoot, 'prepare_instance', autospec=True)
    @mock.patch.object(fake.FakeBoot, 'clean_up_ramdisk', autospec=True)
    @mock.patch.object(manager_utils, 'node_power_action', autospec=True)
    def test_agent_unrescue_no_manage_agent_boot(self, mock_node_power_action,
                                                 mock_clean_ramdisk,
                                                 mock_prepare_instance,
                                                 mock_conf_tenant_net,
                                                 mock_remove_rescue_net):
        self.config(manage_agent_boot=False, group='agent')
        with task_manager.acquire(self.context, self.node.uuid) as task:
            result = task.driver.rescue.unrescue(task)
            mock_node_power_action.assert_has_calls(
                [mock.call(task, states.POWER_OFF),
                 mock.call(task, states.POWER_ON)])
            self.assertFalse(mock_clean_ramdisk.called)
            mock_remove_rescue_net.assert_called_once_with(mock.ANY, task)
            mock_conf_tenant_net.assert_called_once_with(mock.ANY, task)
            mock_prepare_instance.assert_called_once_with(mock.ANY, task)
            self.assertEqual(states.ACTIVE, result)

    @mock.patch.object(fake.FakeBoot, 'clean_up_instance', autospec=True)
    @mock.patch.object(manager_utils, 'node_power_action', autospec=True)
    def test_agent_rescue_power_on(self, mock_node_power_action,
                                   mock_clean_up_instance):
        self.node.power_state = states.POWER_ON
        mock_clean_up_instance.side_effect = exception.IronicException()
        with task_manager.acquire(self.context, self.node.uuid) as task:
            self.assertRaises(exception.IronicException,
                              task.driver.rescue.rescue, task)
            mock_node_power_action.assert_called_once_with(task,
                                                           states.POWER_OFF)
            task.node.refresh()
            # Ensure that our stored power state while the lock is still
            # being held, shows as POWER_ON to an external reader, such
            # as the API.
            self.assertEqual(states.POWER_ON, task.node.power_state)

    @mock.patch.object(fake.FakeBoot, 'clean_up_ramdisk', autospec=True)
    @mock.patch.object(manager_utils, 'node_power_action', autospec=True)
    def test_agent_unrescue_power_on(self, mock_node_power_action,
                                     mock_clean_ramdisk):
        self.node.power_state = states.POWER_ON
        mock_clean_ramdisk.side_effect = exception.IronicException()
        with task_manager.acquire(self.context, self.node.uuid) as task:
            self.assertRaises(exception.IronicException,
                              task.driver.rescue.unrescue, task)
            mock_node_power_action.assert_called_once_with(task,
                                                           states.POWER_OFF)
            task.node.refresh()
            # Ensure that our stored power state while the lock is still
            # being held, shows as POWER_ON to an external reader, such
            # as the API.
            self.assertEqual(states.POWER_ON, task.node.power_state)

    @mock.patch.object(flat_network.FlatNetwork, 'validate_rescue',
                       autospec=True)
    @mock.patch.object(fake.FakeBoot, 'validate', autospec=True)
    @mock.patch.object(fake.FakeBoot, 'validate_rescue', autospec=True)
    def test_agent_rescue_validate(self, mock_boot_validate_rescue,
                                   mock_boot_validate,
                                   mock_validate_network):
        with task_manager.acquire(self.context, self.node.uuid) as task:
            task.driver.rescue.validate(task)
            mock_validate_network.assert_called_once_with(mock.ANY, task)
            mock_boot_validate.assert_called_once_with(mock.ANY, task)
            mock_boot_validate_rescue.assert_called_once_with(mock.ANY, task)

    @mock.patch.object(flat_network.FlatNetwork, 'validate_rescue',
                       autospec=True)
    @mock.patch.object(fake.FakeBoot, 'validate', autospec=True)
    @mock.patch.object(fake.FakeBoot, 'validate_rescue', autospec=True)
    def test_agent_rescue_validate_no_manage_agent(self,
                                                   mock_boot_validate_rescue,
                                                   mock_boot_validate,
                                                   mock_rescuing_net):
        self.config(manage_agent_boot=False, group='agent')
        with task_manager.acquire(self.context, self.node.uuid) as task:
            task.driver.rescue.validate(task)
            mock_rescuing_net.assert_called_once_with(mock.ANY, task)
            self.assertFalse(mock_boot_validate.called)
            self.assertFalse(mock_boot_validate_rescue.called)

    @mock.patch.object(flat_network.FlatNetwork, 'validate_rescue',
                       autospec=True)
    @mock.patch.object(fake.FakeBoot, 'validate_rescue', autospec=True)
    def test_agent_rescue_validate_fails_no_rescue_password(
            self, mock_boot_validate, mock_rescuing_net):
        instance_info = self.node.instance_info
        del instance_info['rescue_password']
        self.node.instance_info = instance_info
        self.node.save()
        with task_manager.acquire(self.context, self.node.uuid) as task:
            self.assertRaisesRegex(exception.MissingParameterValue,
                                   'Node.*missing.*rescue_password',
                                   task.driver.rescue.validate, task)
            mock_rescuing_net.assert_called_once_with(mock.ANY, task)
            mock_boot_validate.assert_called_once_with(mock.ANY, task)

    @mock.patch.object(flat_network.FlatNetwork, 'validate_rescue',
                       autospec=True)
    @mock.patch.object(fake.FakeBoot, 'validate_rescue', autospec=True)
    def test_agent_rescue_validate_fails_empty_rescue_password(
            self, mock_boot_validate, mock_rescuing_net):
        instance_info = self.node.instance_info
        instance_info['rescue_password'] = "    "
        self.node.instance_info = instance_info
        self.node.save()
        with task_manager.acquire(self.context, self.node.uuid) as task:
            self.assertRaisesRegex(exception.InvalidParameterValue,
                                   "'instance_info/rescue_password'.*empty",
                                   task.driver.rescue.validate, task)
            mock_rescuing_net.assert_called_once_with(mock.ANY, task)
            mock_boot_validate.assert_called_once_with(mock.ANY, task)

    @mock.patch.object(flat_network.FlatNetwork, 'remove_rescuing_network',
                       spec_set=True, autospec=True)
    @mock.patch.object(fake.FakeBoot, 'clean_up_ramdisk', autospec=True)
    def test_agent_rescue_clean_up(self, mock_clean_ramdisk,
                                   mock_remove_rescue_net):
        with task_manager.acquire(self.context, self.node.uuid) as task:
            task.driver.rescue.clean_up(task)
            self.assertNotIn('rescue_password', task.node.instance_info)
            mock_clean_ramdisk.assert_called_once_with(
                mock.ANY, task)
            mock_remove_rescue_net.assert_called_once_with(mock.ANY, task)

    @mock.patch.object(flat_network.FlatNetwork, 'remove_rescuing_network',
                       spec_set=True, autospec=True)
    @mock.patch.object(fake.FakeBoot, 'clean_up_ramdisk', autospec=True)
    def test_agent_rescue_clean_up_no_manage_boot(self, mock_clean_ramdisk,
                                                  mock_remove_rescue_net):
        self.config(manage_agent_boot=False, group='agent')
        with task_manager.acquire(self.context, self.node.uuid) as task:
            task.driver.rescue.clean_up(task)
            self.assertNotIn('rescue_password', task.node.instance_info)
            self.assertFalse(mock_clean_ramdisk.called)
            mock_remove_rescue_net.assert_called_once_with(mock.ANY, task)

    @mock.patch.object(manager_utils, 'restore_power_state_if_needed',
                       autospec=True)
    @mock.patch.object(manager_utils, 'power_on_node_if_needed',
                       autospec=True)
    @mock.patch.object(flat_network.FlatNetwork, 'add_rescuing_network',
                       spec_set=True, autospec=True)
    @mock.patch.object(flat_network.FlatNetwork, 'unconfigure_tenant_networks',
                       spec_set=True, autospec=True)
    @mock.patch.object(fake.FakeBoot, 'prepare_ramdisk', autospec=True)
    @mock.patch.object(fake.FakeBoot, 'clean_up_instance', autospec=True)
    @mock.patch.object(deploy_utils, 'build_agent_options', autospec=True)
    @mock.patch.object(manager_utils, 'node_power_action', autospec=True)
    def test_agent_rescue_with_smartnic_port(
            self, mock_node_power_action, mock_build_agent_opts,
            mock_clean_up_instance, mock_prepare_ramdisk,
            mock_unconf_tenant_net, mock_add_rescue_net,
            power_on_node_if_needed_mock, restore_power_state_mock):
        self.config(manage_agent_boot=True, group='agent')
        mock_build_agent_opts.return_value = {'ipa-api-url': 'fake-api'}
        with task_manager.acquire(self.context, self.node.uuid) as task:
            power_on_node_if_needed_mock.return_value = states.POWER_OFF
            result = task.driver.rescue.rescue(task)
            mock_node_power_action.assert_has_calls(
                [mock.call(task, states.POWER_OFF),
                 mock.call(task, states.POWER_ON)])
            mock_clean_up_instance.assert_called_once_with(mock.ANY, task)
            mock_unconf_tenant_net.assert_called_once_with(mock.ANY, task)
            mock_add_rescue_net.assert_called_once_with(mock.ANY, task)
            mock_build_agent_opts.assert_called_once_with(task.node)
            mock_prepare_ramdisk.assert_called_once_with(
                mock.ANY, task, {'ipa-api-url': 'fake-api'})
            self.assertEqual(states.RESCUEWAIT, result)
            power_on_node_if_needed_mock.assert_called_once_with(task)
            restore_power_state_mock.assert_called_once_with(
                task, states.POWER_OFF)

    @mock.patch.object(manager_utils, 'restore_power_state_if_needed',
                       autospec=True)
    @mock.patch.object(manager_utils, 'power_on_node_if_needed',
                       autospec=True)
    @mock.patch.object(flat_network.FlatNetwork, 'remove_rescuing_network',
                       spec_set=True, autospec=True)
    @mock.patch.object(flat_network.FlatNetwork, 'configure_tenant_networks',
                       spec_set=True, autospec=True)
    @mock.patch.object(fake.FakeBoot, 'prepare_instance', autospec=True)
    @mock.patch.object(fake.FakeBoot, 'clean_up_ramdisk', autospec=True)
    @mock.patch.object(manager_utils, 'node_power_action', autospec=True)
    def test_agent_unrescue_with_smartnic_port(
            self, mock_node_power_action, mock_clean_ramdisk,
            mock_prepare_instance, mock_conf_tenant_net,
            mock_remove_rescue_net, power_on_node_if_needed_mock,
            restore_power_state_mock):
        self.config(manage_agent_boot=True, group='agent')
        with task_manager.acquire(self.context, self.node.uuid) as task:
            power_on_node_if_needed_mock.return_value = states.POWER_OFF
            result = task.driver.rescue.unrescue(task)
            mock_node_power_action.assert_has_calls(
                [mock.call(task, states.POWER_OFF),
                 mock.call(task, states.POWER_ON)])
            mock_clean_ramdisk.assert_called_once_with(
                mock.ANY, task)
            mock_remove_rescue_net.assert_called_once_with(mock.ANY, task)
            mock_conf_tenant_net.assert_called_once_with(mock.ANY, task)
            mock_prepare_instance.assert_called_once_with(mock.ANY, task)
            self.assertEqual(states.ACTIVE, result)
            self.assertEqual(2, power_on_node_if_needed_mock.call_count)
            self.assertEqual(2, power_on_node_if_needed_mock.call_count)
            restore_power_state_mock.assert_has_calls(
                [mock.call(task, states.POWER_OFF),
                 mock.call(task, states.POWER_OFF)])

    @mock.patch.object(manager_utils, 'restore_power_state_if_needed',
                       autospec=True)
    @mock.patch.object(manager_utils, 'power_on_node_if_needed',
                       autospec=True)
    @mock.patch.object(flat_network.FlatNetwork, 'remove_rescuing_network',
                       spec_set=True, autospec=True)
    @mock.patch.object(fake.FakeBoot, 'clean_up_ramdisk', autospec=True)
    def test_agent_rescue_clean_up_smartnic(
            self, mock_clean_ramdisk, mock_remove_rescue_net,
            power_on_node_if_needed_mock, restore_power_state_mock):
        with task_manager.acquire(self.context, self.node.uuid) as task:
            power_on_node_if_needed_mock.return_value = states.POWER_OFF
            task.driver.rescue.clean_up(task)
            self.assertNotIn('rescue_password', task.node.instance_info)
            mock_clean_ramdisk.assert_called_once_with(
                mock.ANY, task)
            mock_remove_rescue_net.assert_called_once_with(mock.ANY, task)
            restore_power_state_mock.assert_called_once_with(
                task, states.POWER_OFF)
