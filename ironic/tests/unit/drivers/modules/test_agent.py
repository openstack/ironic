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
from ironic.common import images
from ironic.common import raid
from ironic.common import states
from ironic.conductor import task_manager
from ironic.conductor import utils as manager_utils
from ironic.drivers.modules import agent
from ironic.drivers.modules import agent_base_vendor
from ironic.drivers.modules import agent_client
from ironic.drivers.modules import deploy_utils
from ironic.drivers.modules import fake
from ironic.drivers.modules import pxe
from ironic.drivers import utils as driver_utils
from ironic.tests.unit.conductor import mgr_utils
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
                                                  driver='fake_agent')
        dhcp_factory.DHCPFactory._dhcp_provider = None

    @mock.patch.object(image_service, 'GlanceImageService', autospec=True)
    def test_build_instance_info_for_deploy_glance_image(self, glance_mock):
        i_info = self.node.instance_info
        i_info['image_source'] = '733d1c44-a2ea-414b-aca7-69decf20d810'
        driver_internal_info = self.node.driver_internal_info
        driver_internal_info['is_whole_disk_image'] = True
        self.node.driver_internal_info = driver_internal_info
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

    @mock.patch.object(deploy_utils, 'parse_instance_info', autospec=True)
    @mock.patch.object(image_service, 'GlanceImageService', autospec=True)
    def test_build_instance_info_for_deploy_glance_partition_image(
            self, glance_mock, parse_instance_info_mock):
        i_info = {}
        i_info['image_source'] = '733d1c44-a2ea-414b-aca7-69decf20d810'
        i_info['kernel'] = '13ce5a56-1de3-4916-b8b2-be778645d003'
        i_info['ramdisk'] = 'a5a370a8-1b39-433f-be63-2c7d708e4b4e'
        i_info['root_gb'] = 5
        i_info['swap_mb'] = 4
        i_info['ephemeral_gb'] = 0
        i_info['ephemeral_format'] = None
        i_info['configdrive'] = 'configdrive'
        driver_internal_info = self.node.driver_internal_info
        driver_internal_info['is_whole_disk_image'] = False
        self.node.driver_internal_info = driver_internal_info
        self.node.instance_info = i_info
        self.node.save()

        image_info = {'checksum': 'aa', 'disk_format': 'qcow2',
                      'container_format': 'bare',
                      'properties': {'kernel_id': 'kernel',
                                     'ramdisk_id': 'ramdisk'}}
        glance_mock.return_value.show = mock.MagicMock(spec_set=[],
                                                       return_value=image_info)
        glance_obj_mock = glance_mock.return_value
        glance_obj_mock.swift_temp_url.return_value = 'temp-url'
        parse_instance_info_mock.return_value = {'swap_mb': 4}
        image_source = '733d1c44-a2ea-414b-aca7-69decf20d810'
        expected_i_info = {'root_gb': 5,
                           'swap_mb': 4,
                           'ephemeral_gb': 0,
                           'ephemeral_format': None,
                           'configdrive': 'configdrive',
                           'image_source': image_source,
                           'image_url': 'temp-url',
                           'kernel': 'kernel',
                           'ramdisk': 'ramdisk',
                           'image_type': 'partition',
                           'image_checksum': 'aa',
                           'image_container_format': 'bare',
                           'image_disk_format': 'qcow2'}
        mgr_utils.mock_the_extension_manager(driver='fake_agent')
        with task_manager.acquire(
                self.context, self.node.uuid, shared=False) as task:

            info = agent.build_instance_info_for_deploy(task)

            glance_mock.assert_called_once_with(version=2,
                                                context=task.context)
            glance_mock.return_value.show.assert_called_once_with(
                self.node.instance_info['image_source'])
            glance_mock.return_value.swift_temp_url.assert_called_once_with(
                image_info)
            image_type = task.node.instance_info['image_type']
            self.assertEqual('partition', image_type)
            self.assertEqual('kernel', info['kernel'])
            self.assertEqual('ramdisk', info['ramdisk'])
            self.assertEqual(expected_i_info, info)
            parse_instance_info_mock.assert_called_once_with(task.node)

    @mock.patch.object(image_service.HttpImageService, 'validate_href',
                       autospec=True)
    def test_build_instance_info_for_deploy_nonglance_image(
            self, validate_href_mock):
        i_info = self.node.instance_info
        driver_internal_info = self.node.driver_internal_info
        i_info['image_source'] = 'http://image-ref'
        i_info['image_checksum'] = 'aa'
        i_info['root_gb'] = 10
        i_info['image_checksum'] = 'aa'
        driver_internal_info['is_whole_disk_image'] = True
        self.node.instance_info = i_info
        self.node.driver_internal_info = driver_internal_info
        self.node.save()

        mgr_utils.mock_the_extension_manager(driver='fake_agent')
        with task_manager.acquire(
                self.context, self.node.uuid, shared=False) as task:

            info = agent.build_instance_info_for_deploy(task)

            self.assertEqual(self.node.instance_info['image_source'],
                             info['image_url'])
            validate_href_mock.assert_called_once_with(
                mock.ANY, 'http://image-ref')

    @mock.patch.object(deploy_utils, 'parse_instance_info', autospec=True)
    @mock.patch.object(image_service.HttpImageService, 'validate_href',
                       autospec=True)
    def test_build_instance_info_for_deploy_nonglance_partition_image(
            self, validate_href_mock, parse_instance_info_mock):
        i_info = {}
        driver_internal_info = self.node.driver_internal_info
        i_info['image_source'] = 'http://image-ref'
        i_info['kernel'] = 'http://kernel-ref'
        i_info['ramdisk'] = 'http://ramdisk-ref'
        i_info['image_checksum'] = 'aa'
        i_info['root_gb'] = 10
        i_info['configdrive'] = 'configdrive'
        driver_internal_info['is_whole_disk_image'] = False
        self.node.instance_info = i_info
        self.node.driver_internal_info = driver_internal_info
        self.node.save()

        mgr_utils.mock_the_extension_manager(driver='fake_agent')
        validate_href_mock.side_effect = ['http://image-ref',
                                          'http://kernel-ref',
                                          'http://ramdisk-ref']
        parse_instance_info_mock.return_value = {'swap_mb': 5}
        expected_i_info = {'image_source': 'http://image-ref',
                           'image_url': 'http://image-ref',
                           'image_type': 'partition',
                           'kernel': 'http://kernel-ref',
                           'ramdisk': 'http://ramdisk-ref',
                           'image_checksum': 'aa',
                           'root_gb': 10,
                           'swap_mb': 5,
                           'configdrive': 'configdrive'}
        with task_manager.acquire(
                self.context, self.node.uuid, shared=False) as task:

            info = agent.build_instance_info_for_deploy(task)

            self.assertEqual(self.node.instance_info['image_source'],
                             info['image_url'])
            validate_href_mock.assert_called_once_with(
                mock.ANY, 'http://image-ref')
            self.assertEqual('partition', info['image_type'])
            self.assertEqual(expected_i_info, info)
            parse_instance_info_mock.assert_called_once_with(task.node)

    @mock.patch.object(image_service.HttpImageService, 'validate_href',
                       autospec=True)
    def test_build_instance_info_for_deploy_nonsupported_image(
            self, validate_href_mock):
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

    @mock.patch.object(images, 'image_show', autospec=True)
    def test_check_image_size(self, show_mock):
        show_mock.return_value = {
            'size': 10 * 1024 * 1024,
            'disk_format': 'qcow2',
        }
        mgr_utils.mock_the_extension_manager(driver='fake_agent')
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.node.properties['memory_mb'] = 10
            agent.check_image_size(task, 'fake-image')
            show_mock.assert_called_once_with(self.context, 'fake-image')

    @mock.patch.object(images, 'image_show', autospec=True)
    def test_check_image_size_without_memory_mb(self, show_mock):
        mgr_utils.mock_the_extension_manager(driver='fake_agent')
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.node.properties.pop('memory_mb', None)
            agent.check_image_size(task, 'fake-image')
            self.assertFalse(show_mock.called)

    @mock.patch.object(images, 'image_show', autospec=True)
    def test_check_image_size_fail(self, show_mock):
        show_mock.return_value = {
            'size': 11 * 1024 * 1024,
            'disk_format': 'qcow2',
        }
        mgr_utils.mock_the_extension_manager(driver='fake_agent')
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.node.properties['memory_mb'] = 10
            self.assertRaises(exception.InvalidParameterValue,
                              agent.check_image_size,
                              task, 'fake-image')
            show_mock.assert_called_once_with(self.context, 'fake-image')

    @mock.patch.object(images, 'image_show', autospec=True)
    def test_check_image_size_fail_by_agent_consumed_memory(self, show_mock):
        self.config(memory_consumed_by_agent=2, group='agent')
        show_mock.return_value = {
            'size': 9 * 1024 * 1024,
            'disk_format': 'qcow2',
        }
        mgr_utils.mock_the_extension_manager(driver='fake_agent')
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.node.properties['memory_mb'] = 10
            self.assertRaises(exception.InvalidParameterValue,
                              agent.check_image_size,
                              task, 'fake-image')
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
        mgr_utils.mock_the_extension_manager(driver='fake_agent')
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.node.properties['memory_mb'] = 10
            agent.check_image_size(task, 'fake-image')
            show_mock.assert_called_once_with(self.context, 'fake-image')

    @mock.patch.object(images, 'image_show', autospec=True)
    def test_check_image_size_raw_stream_disabled(self, show_mock):
        CONF.set_override('stream_raw_images', False, 'agent')
        show_mock.return_value = {
            'size': 15 * 1024 * 1024,
            'disk_format': 'raw',
        }
        mgr_utils.mock_the_extension_manager(driver='fake_agent')
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.node.properties['memory_mb'] = 10
            # Image is raw but stream is disabled, so test should fail since
            # the image is bigger than the RAM size
            self.assertRaises(exception.InvalidParameterValue,
                              agent.check_image_size,
                              task, 'fake-image')
            show_mock.assert_called_once_with(self.context, 'fake-image')


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
        self.ports = [
            object_utils.create_test_port(self.context, node_id=self.node.id)]
        dhcp_factory.DHCPFactory._dhcp_provider = None

    def test_get_properties(self):
        expected = agent.COMMON_PROPERTIES
        self.assertEqual(expected, self.driver.get_properties())

    @mock.patch.object(deploy_utils, 'validate_capabilities',
                       spec_set=True, autospec=True)
    @mock.patch.object(images, 'image_show', autospec=True)
    @mock.patch.object(pxe.PXEBoot, 'validate', autospec=True)
    def test_validate(self, pxe_boot_validate_mock, show_mock,
                      validate_capability_mock):
        with task_manager.acquire(
                self.context, self.node['uuid'], shared=False) as task:
            self.driver.validate(task)
            pxe_boot_validate_mock.assert_called_once_with(
                task.driver.boot, task)
            show_mock.assert_called_once_with(self.context, 'fake-image')
            validate_capability_mock.assert_called_once_with(task.node)

    @mock.patch.object(deploy_utils, 'validate_capabilities',
                       spec_set=True, autospec=True)
    @mock.patch.object(images, 'image_show', autospec=True)
    @mock.patch.object(pxe.PXEBoot, 'validate', autospec=True)
    def test_validate_driver_info_manage_agent_boot_false(
            self, pxe_boot_validate_mock, show_mock,
            validate_capability_mock):

        self.config(manage_agent_boot=False, group='agent')
        self.node.driver_info = {}
        self.node.save()
        with task_manager.acquire(
                self.context, self.node['uuid'], shared=False) as task:
            self.driver.validate(task)
            self.assertFalse(pxe_boot_validate_mock.called)
            show_mock.assert_called_once_with(self.context, 'fake-image')
            validate_capability_mock.assert_called_once_with(task.node)

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

    @mock.patch.object(images, 'image_show', autospec=True)
    @mock.patch.object(pxe.PXEBoot, 'validate', autospec=True)
    def test_validate_invalid_root_device_hints(
            self, pxe_boot_validate_mock, show_mock):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            task.node.properties['root_device'] = {'size': 'not-int'}
            self.assertRaises(exception.InvalidParameterValue,
                              task.driver.deploy.validate, task)
            pxe_boot_validate_mock.assert_called_once_with(
                task.driver.boot, task)
            show_mock.assert_called_once_with(self.context, 'fake-image')

    @mock.patch.object(images, 'image_show', autospec=True)
    @mock.patch.object(pxe.PXEBoot, 'validate', autospec=True)
    def test_validate_invalid_proxies(self, pxe_boot_validate_mock, show_mock):
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
            show_mock.assert_called_once_with(self.context, 'fake-image')

    @mock.patch('ironic.conductor.utils.node_power_action', autospec=True)
    def test_deploy(self, power_mock):
        with task_manager.acquire(
                self.context, self.node['uuid'], shared=False) as task:
            driver_return = self.driver.deploy(task)
            self.assertEqual(driver_return, states.DEPLOYWAIT)
            power_mock.assert_called_once_with(task, states.REBOOT)

    @mock.patch('ironic.drivers.modules.network.flat.FlatNetwork.'
                'unconfigure_tenant_networks', autospec=True)
    @mock.patch('ironic.conductor.utils.node_power_action', autospec=True)
    def test_tear_down(self, power_mock, unconfigure_tenant_nets_mock):
        with task_manager.acquire(
                self.context, self.node['uuid'], shared=False) as task:
            driver_return = self.driver.tear_down(task)
            power_mock.assert_called_once_with(task, states.POWER_OFF)
            self.assertEqual(driver_return, states.DELETED)
            unconfigure_tenant_nets_mock.assert_called_once_with(mock.ANY,
                                                                 task)

    @mock.patch.object(pxe.PXEBoot, 'prepare_ramdisk')
    @mock.patch.object(deploy_utils, 'build_agent_options')
    @mock.patch.object(agent, 'build_instance_info_for_deploy')
    @mock.patch('ironic.drivers.modules.network.flat.FlatNetwork.'
                'add_provisioning_network', autospec=True)
    def test_prepare(self, add_provisioning_net_mock, build_instance_info_mock,
                     build_options_mock, pxe_prepare_ramdisk_mock):
        with task_manager.acquire(
                self.context, self.node['uuid'], shared=False) as task:
            task.node.provision_state = states.DEPLOYING
            build_instance_info_mock.return_value = {'foo': 'bar'}
            build_options_mock.return_value = {'a': 'b'}

            self.driver.prepare(task)

            build_instance_info_mock.assert_called_once_with(task)
            build_options_mock.assert_called_once_with(task.node)
            pxe_prepare_ramdisk_mock.assert_called_once_with(
                task, {'a': 'b'})
            add_provisioning_net_mock.assert_called_once_with(mock.ANY, task)

        self.node.refresh()
        self.assertEqual('bar', self.node.instance_info['foo'])

    @mock.patch.object(pxe.PXEBoot, 'prepare_ramdisk')
    @mock.patch.object(deploy_utils, 'build_agent_options')
    @mock.patch.object(agent, 'build_instance_info_for_deploy')
    def test_prepare_manage_agent_boot_false(
            self, build_instance_info_mock, build_options_mock,
            pxe_prepare_ramdisk_mock):
        self.config(group='agent', manage_agent_boot=False)
        with task_manager.acquire(
                self.context, self.node['uuid'], shared=False) as task:
            task.node.provision_state = states.DEPLOYING
            build_instance_info_mock.return_value = {'foo': 'bar'}

            self.driver.prepare(task)

            build_instance_info_mock.assert_called_once_with(task)
            self.assertFalse(build_options_mock.called)
            self.assertFalse(pxe_prepare_ramdisk_mock.called)

        self.node.refresh()
        self.assertEqual('bar', self.node.instance_info['foo'])

    @mock.patch('ironic.drivers.modules.network.flat.FlatNetwork.'
                'add_provisioning_network', autospec=True)
    @mock.patch.object(pxe.PXEBoot, 'prepare_ramdisk')
    @mock.patch.object(deploy_utils, 'build_agent_options')
    @mock.patch.object(agent, 'build_instance_info_for_deploy')
    def test_prepare_active(
            self, build_instance_info_mock, build_options_mock,
            pxe_prepare_ramdisk_mock, add_provisioning_net_mock):
        with task_manager.acquire(
                self.context, self.node['uuid'], shared=False) as task:
            task.node.provision_state = states.ACTIVE

            self.driver.prepare(task)

            self.assertFalse(build_instance_info_mock.called)
            self.assertFalse(build_options_mock.called)
            self.assertFalse(pxe_prepare_ramdisk_mock.called)
            self.assertFalse(add_provisioning_net_mock.called)

    @mock.patch('ironic.drivers.modules.network.flat.FlatNetwork.'
                'add_provisioning_network', autospec=True)
    @mock.patch.object(pxe.PXEBoot, 'prepare_ramdisk')
    @mock.patch.object(deploy_utils, 'build_agent_options')
    @mock.patch.object(agent, 'build_instance_info_for_deploy')
    def test_prepare_adopting(
            self, build_instance_info_mock, build_options_mock,
            pxe_prepare_ramdisk_mock, add_provisioning_net_mock):
        with task_manager.acquire(
                self.context, self.node['uuid'], shared=False) as task:
            task.node.provision_state = states.ADOPTING

            self.driver.prepare(task)

            self.assertFalse(build_instance_info_mock.called)
            self.assertFalse(build_options_mock.called)
            self.assertFalse(pxe_prepare_ramdisk_mock.called)
            self.assertFalse(add_provisioning_net_mock.called)

    @mock.patch('ironic.common.dhcp_factory.DHCPFactory._set_dhcp_provider')
    @mock.patch('ironic.common.dhcp_factory.DHCPFactory.clean_dhcp')
    @mock.patch.object(pxe.PXEBoot, 'clean_up_ramdisk')
    def test_clean_up(self, pxe_clean_up_ramdisk_mock, clean_dhcp_mock,
                      set_dhcp_provider_mock):
        with task_manager.acquire(
                self.context, self.node['uuid'], shared=False) as task:
            self.driver.clean_up(task)
            pxe_clean_up_ramdisk_mock.assert_called_once_with(task)
            set_dhcp_provider_mock.assert_called_once_with()
            clean_dhcp_mock.assert_called_once_with(task)

    @mock.patch('ironic.common.dhcp_factory.DHCPFactory._set_dhcp_provider')
    @mock.patch('ironic.common.dhcp_factory.DHCPFactory.clean_dhcp')
    @mock.patch.object(pxe.PXEBoot, 'clean_up_ramdisk')
    def test_clean_up_manage_agent_boot_false(self, pxe_clean_up_ramdisk_mock,
                                              clean_dhcp_mock,
                                              set_dhcp_provider_mock):
        with task_manager.acquire(
                self.context, self.node['uuid'], shared=False) as task:
            self.config(group='agent', manage_agent_boot=False)
            self.driver.clean_up(task)
            self.assertFalse(pxe_clean_up_ramdisk_mock.called)
            set_dhcp_provider_mock.assert_called_once_with()
            clean_dhcp_mock.assert_called_once_with(task)

    @mock.patch('ironic.drivers.modules.deploy_utils.agent_get_clean_steps',
                autospec=True)
    def test_get_clean_steps(self, mock_get_clean_steps):
        # Test getting clean steps
        mock_steps = [{'priority': 10, 'interface': 'deploy',
                       'step': 'erase_devices'}]
        mock_get_clean_steps.return_value = mock_steps
        with task_manager.acquire(self.context, self.node.uuid) as task:
            steps = self.driver.get_clean_steps(task)
            mock_get_clean_steps.assert_called_once_with(
                task, interface='deploy',
                override_priorities={'erase_devices': None,
                                     'erase_devices_metadata': None})
        self.assertEqual(mock_steps, steps)

    @mock.patch('ironic.drivers.modules.deploy_utils.agent_get_clean_steps',
                autospec=True)
    def test_get_clean_steps_config_priority(self, mock_get_clean_steps):
        # Test that we can override the priority of get clean steps
        # Use 0 because it is an edge case (false-y) and used in devstack
        self.config(erase_devices_priority=0, group='deploy')
        self.config(erase_devices_metadata_priority=0, group='deploy')
        mock_steps = [{'priority': 10, 'interface': 'deploy',
                       'step': 'erase_devices'}]
        mock_get_clean_steps.return_value = mock_steps
        with task_manager.acquire(self.context, self.node.uuid) as task:
            self.driver.get_clean_steps(task)
            mock_get_clean_steps.assert_called_once_with(
                task, interface='deploy',
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

    @mock.patch.object(deploy_utils, 'tear_down_inband_cleaning',
                       autospec=True)
    def test_tear_down_cleaning(self, tear_down_cleaning_mock):
        with task_manager.acquire(self.context, self.node.uuid) as task:
            self.driver.tear_down_cleaning(task)
            tear_down_cleaning_mock.assert_called_once_with(
                task, manage_boot=True)

    @mock.patch.object(deploy_utils, 'tear_down_inband_cleaning',
                       autospec=True)
    def test_tear_down_cleaning_manage_agent_boot_false(
            self, tear_down_cleaning_mock):
        self.config(group='agent', manage_agent_boot=False)
        with task_manager.acquire(self.context, self.node.uuid) as task:
            self.driver.tear_down_cleaning(task)
            tear_down_cleaning_mock.assert_called_once_with(
                task, manage_boot=False)

    def test_heartbeat(self):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            self.driver.heartbeat(task, 'url')
            self.assertFalse(task.shared)


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

    def _test_continue_deploy(self, additional_driver_info=None,
                              additional_expected_image_info=None):
        self.node.provision_state = states.DEPLOYWAIT
        self.node.target_provision_state = states.ACTIVE
        driver_info = self.node.driver_info
        driver_info.update(additional_driver_info or {})
        self.node.driver_info = driver_info
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

    def test_continue_deploy(self):
        self._test_continue_deploy()

    def test_continue_deploy_with_proxies(self):
        self._test_continue_deploy(
            additional_driver_info={'image_https_proxy': 'https://spam.ni',
                                    'image_http_proxy': 'spam.ni',
                                    'image_no_proxy': '.eggs.com'},
            additional_expected_image_info={
                'proxies': {'https': 'https://spam.ni',
                            'http': 'spam.ni'},
                'no_proxy': '.eggs.com'}
        )

    def test_continue_deploy_with_no_proxy_without_proxies(self):
        self._test_continue_deploy(
            additional_driver_info={'image_no_proxy': '.eggs.com'}
        )

    def test_continue_deploy_image_source_is_url(self):
        instance_info = self.node.instance_info
        instance_info['image_source'] = 'http://example.com/woof.img'
        self.node.instance_info = instance_info
        self._test_continue_deploy(
            additional_expected_image_info={
                'id': 'woof.img'
            }
        )

    def test_continue_deploy_partition_image(self):
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

    @mock.patch.object(agent.AgentVendorInterface, '_get_uuid_from_result',
                       autospec=True)
    @mock.patch.object(manager_utils, 'node_power_action', autospec=True)
    @mock.patch.object(fake.FakePower, 'get_power_state',
                       spec=types.FunctionType)
    @mock.patch.object(agent_client.AgentClient, 'power_off',
                       spec=types.FunctionType)
    @mock.patch.object(pxe.PXEBoot, 'prepare_instance',
                       autospec=True)
    @mock.patch('ironic.drivers.modules.agent.AgentVendorInterface'
                '.check_deploy_success', autospec=True)
    @mock.patch.object(pxe.PXEBoot, 'clean_up_ramdisk', autospec=True)
    def test_reboot_to_instance(self, clean_pxe_mock, check_deploy_mock,
                                prepare_mock, power_off_mock,
                                get_power_state_mock, node_power_action_mock,
                                uuid_mock):
        check_deploy_mock.return_value = None
        uuid_mock.return_value = 'root_uuid'
        self.node.provision_state = states.DEPLOYWAIT
        self.node.target_provision_state = states.ACTIVE
        self.node.save()
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            get_power_state_mock.return_value = states.POWER_OFF
            task.node.driver_internal_info['is_whole_disk_image'] = True

            self.passthru.reboot_to_instance(task)

            clean_pxe_mock.assert_called_once_with(task.driver.boot, task)
            check_deploy_mock.assert_called_once_with(mock.ANY, task.node)
            power_off_mock.assert_called_once_with(task.node)
            get_power_state_mock.assert_called_once_with(task)
            node_power_action_mock.assert_called_once_with(
                task, states.POWER_ON)
            self.assertFalse(prepare_mock.called)
            self.assertEqual(states.ACTIVE, task.node.provision_state)
            self.assertEqual(states.NOSTATE, task.node.target_provision_state)
            self.assertNotIn('root_uuid_or_disk_id',
                             task.node.driver_internal_info)
            self.assertFalse(uuid_mock.called)

    @mock.patch.object(deploy_utils, 'get_boot_mode_for_deploy', autospec=True)
    @mock.patch.object(agent.AgentVendorInterface, '_get_uuid_from_result',
                       autospec=True)
    @mock.patch.object(manager_utils, 'node_power_action', autospec=True)
    @mock.patch.object(fake.FakePower, 'get_power_state',
                       spec=types.FunctionType)
    @mock.patch.object(agent_client.AgentClient, 'power_off',
                       spec=types.FunctionType)
    @mock.patch.object(pxe.PXEBoot, 'prepare_instance',
                       autospec=True)
    @mock.patch('ironic.drivers.modules.agent.AgentVendorInterface'
                '.check_deploy_success', autospec=True)
    @mock.patch.object(pxe.PXEBoot, 'clean_up_ramdisk', autospec=True)
    def test_reboot_to_instance_partition_image(self, clean_pxe_mock,
                                                check_deploy_mock,
                                                prepare_mock, power_off_mock,
                                                get_power_state_mock,
                                                node_power_action_mock,
                                                uuid_mock, boot_mode_mock):
        check_deploy_mock.return_value = None
        uuid_mock.return_value = 'root_uuid'
        self.node.provision_state = states.DEPLOYWAIT
        self.node.target_provision_state = states.ACTIVE
        self.node.save()
        boot_mode_mock.return_value = 'bios'
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            get_power_state_mock.return_value = states.POWER_OFF
            task.node.driver_internal_info['is_whole_disk_image'] = False

            self.passthru.reboot_to_instance(task)

            self.assertFalse(clean_pxe_mock.called)
            check_deploy_mock.assert_called_once_with(mock.ANY, task.node)
            power_off_mock.assert_called_once_with(task.node)
            get_power_state_mock.assert_called_once_with(task)
            node_power_action_mock.assert_called_once_with(
                task, states.POWER_ON)
            prepare_mock.assert_called_once_with(task.driver.boot, task)
            self.assertEqual(states.ACTIVE, task.node.provision_state)
            self.assertEqual(states.NOSTATE, task.node.target_provision_state)
            driver_int_info = task.node.driver_internal_info
            self.assertEqual('root_uuid',
                             driver_int_info['root_uuid_or_disk_id']),
            uuid_mock.assert_called_once_with(self.passthru, task, 'root_uuid')
            boot_mode_mock.assert_called_once_with(task.node)

    @mock.patch.object(agent.AgentVendorInterface, '_get_uuid_from_result',
                       autospec=True)
    @mock.patch.object(manager_utils, 'node_power_action', autospec=True)
    @mock.patch.object(fake.FakePower, 'get_power_state',
                       spec=types.FunctionType)
    @mock.patch.object(agent_client.AgentClient, 'power_off',
                       spec=types.FunctionType)
    @mock.patch.object(pxe.PXEBoot, 'prepare_instance',
                       autospec=True)
    @mock.patch('ironic.drivers.modules.agent.AgentVendorInterface'
                '.check_deploy_success', autospec=True)
    @mock.patch.object(pxe.PXEBoot, 'clean_up_ramdisk', autospec=True)
    def test_reboot_to_instance_boot_none(self, clean_pxe_mock,
                                          check_deploy_mock,
                                          prepare_mock, power_off_mock,
                                          get_power_state_mock,
                                          node_power_action_mock,
                                          uuid_mock):
        check_deploy_mock.return_value = None
        self.node.provision_state = states.DEPLOYWAIT
        self.node.target_provision_state = states.ACTIVE
        self.node.save()
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            get_power_state_mock.return_value = states.POWER_OFF
            task.node.driver_internal_info['is_whole_disk_image'] = True
            task.driver.boot = None

            self.passthru.reboot_to_instance(task)

            self.assertFalse(clean_pxe_mock.called)
            self.assertFalse(prepare_mock.called)
            power_off_mock.assert_called_once_with(task.node)
            check_deploy_mock.assert_called_once_with(mock.ANY, task.node)
            self.assertNotIn('root_uuid_or_disk_id',
                             task.node.driver_internal_info)

            get_power_state_mock.assert_called_once_with(task)
            node_power_action_mock.assert_called_once_with(
                task, states.POWER_ON)
            self.assertEqual(states.ACTIVE, task.node.provision_state)
            self.assertEqual(states.NOSTATE, task.node.target_provision_state)
            self.assertFalse(uuid_mock.called)

    @mock.patch.object(driver_utils, 'collect_ramdisk_logs', autospec=True)
    @mock.patch.object(agent.AgentVendorInterface, '_get_uuid_from_result',
                       autospec=True)
    @mock.patch.object(manager_utils, 'node_power_action', autospec=True)
    @mock.patch.object(fake.FakePower, 'get_power_state',
                       spec=types.FunctionType)
    @mock.patch.object(agent_client.AgentClient, 'power_off',
                       spec=types.FunctionType)
    @mock.patch.object(pxe.PXEBoot, 'prepare_instance',
                       autospec=True)
    @mock.patch('ironic.drivers.modules.agent.AgentVendorInterface'
                '.check_deploy_success', autospec=True)
    @mock.patch.object(pxe.PXEBoot, 'clean_up_ramdisk', autospec=True)
    def test_reboot_to_instance_boot_error(
            self, clean_pxe_mock, check_deploy_mock, prepare_mock,
            power_off_mock, get_power_state_mock, node_power_action_mock,
            uuid_mock, collect_ramdisk_logs_mock):
        check_deploy_mock.return_value = "Error"
        uuid_mock.return_value = None
        self.node.provision_state = states.DEPLOYWAIT
        self.node.target_provision_state = states.ACTIVE
        self.node.save()
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            get_power_state_mock.return_value = states.POWER_OFF
            task.node.driver_internal_info['is_whole_disk_image'] = True
            task.driver.boot = None
            self.passthru.reboot_to_instance(task)

            self.assertFalse(clean_pxe_mock.called)
            self.assertFalse(prepare_mock.called)
            self.assertFalse(power_off_mock.called)
            check_deploy_mock.assert_called_once_with(mock.ANY, task.node)
            self.assertEqual(states.DEPLOYFAIL, task.node.provision_state)
            self.assertEqual(states.ACTIVE, task.node.target_provision_state)
            collect_ramdisk_logs_mock.assert_called_once_with(task.node)

    @mock.patch.object(agent_base_vendor.BaseAgentVendor,
                       'configure_local_boot', autospec=True)
    @mock.patch.object(deploy_utils, 'try_set_boot_device', autospec=True)
    @mock.patch.object(agent.AgentVendorInterface, '_get_uuid_from_result',
                       autospec=True)
    @mock.patch.object(manager_utils, 'node_power_action', autospec=True)
    @mock.patch.object(fake.FakePower, 'get_power_state',
                       spec=types.FunctionType)
    @mock.patch.object(agent_client.AgentClient, 'power_off',
                       spec=types.FunctionType)
    @mock.patch.object(pxe.PXEBoot, 'prepare_instance',
                       autospec=True)
    @mock.patch('ironic.drivers.modules.agent.AgentVendorInterface'
                '.check_deploy_success', autospec=True)
    @mock.patch.object(pxe.PXEBoot, 'clean_up_ramdisk', autospec=True)
    def test_reboot_to_instance_localboot(self, clean_pxe_mock,
                                          check_deploy_mock,
                                          prepare_mock, power_off_mock,
                                          get_power_state_mock,
                                          node_power_action_mock,
                                          uuid_mock,
                                          bootdev_mock,
                                          configure_mock):
        check_deploy_mock.return_value = None
        uuid_mock.side_effect = ['root_uuid', 'efi_uuid']
        self.node.provision_state = states.DEPLOYWAIT
        self.node.target_provision_state = states.ACTIVE
        self.node.save()

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            get_power_state_mock.return_value = states.POWER_OFF
            task.node.driver_internal_info['is_whole_disk_image'] = False
            boot_option = {'capabilities': '{"boot_option": "local"}'}
            task.node.instance_info = boot_option
            self.passthru.reboot_to_instance(task)

            self.assertFalse(clean_pxe_mock.called)
            check_deploy_mock.assert_called_once_with(mock.ANY, task.node)
            self.assertFalse(bootdev_mock.called)
            power_off_mock.assert_called_once_with(task.node)
            get_power_state_mock.assert_called_once_with(task)
            node_power_action_mock.assert_called_once_with(
                task, states.POWER_ON)
            self.assertEqual(states.ACTIVE, task.node.provision_state)
            self.assertEqual(states.NOSTATE, task.node.target_provision_state)

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


class AgentRAIDTestCase(db_base.DbTestCase):

    def setUp(self):
        super(AgentRAIDTestCase, self).setUp()
        mgr_utils.mock_the_extension_manager(driver="fake_agent")
        self.passthru = agent.AgentVendorInterface()
        self.target_raid_config = {
            "logical_disks": [
                {'size_gb': 200, 'raid_level': 0, 'is_root_volume': True},
                {'size_gb': 200, 'raid_level': 5}
            ]}
        self.clean_step = {'step': 'create_configuration',
                           'interface': 'raid'}
        n = {
            'driver': 'fake_agent',
            'instance_info': INSTANCE_INFO,
            'driver_info': DRIVER_INFO,
            'driver_internal_info': DRIVER_INTERNAL_INFO,
            'target_raid_config': self.target_raid_config,
            'clean_step': self.clean_step,
        }
        self.node = object_utils.create_test_node(self.context, **n)

    @mock.patch.object(deploy_utils, 'agent_get_clean_steps', autospec=True)
    def test_get_clean_steps(self, get_steps_mock):
        get_steps_mock.return_value = [
            {'step': 'create_configuration', 'interface': 'raid',
             'priority': 1},
            {'step': 'delete_configuration', 'interface': 'raid',
             'priority': 2}]

        with task_manager.acquire(self.context, self.node.uuid) as task:
            ret = task.driver.raid.get_clean_steps(task)

        self.assertEqual(0, ret[0]['priority'])
        self.assertEqual(0, ret[1]['priority'])

    @mock.patch.object(deploy_utils, 'agent_execute_clean_step',
                       autospec=True)
    def test_create_configuration(self, execute_mock):
        with task_manager.acquire(self.context, self.node.uuid) as task:
            execute_mock.return_value = states.CLEANWAIT

            return_value = task.driver.raid.create_configuration(task)

            self.assertEqual(states.CLEANWAIT, return_value)
            self.assertEqual(
                self.target_raid_config,
                task.node.driver_internal_info['target_raid_config'])
            execute_mock.assert_called_once_with(task, self.clean_step)

    @mock.patch.object(deploy_utils, 'agent_execute_clean_step',
                       autospec=True)
    def test_create_configuration_skip_root(self, execute_mock):
        with task_manager.acquire(self.context, self.node.uuid) as task:
            execute_mock.return_value = states.CLEANWAIT

            return_value = task.driver.raid.create_configuration(
                task, create_root_volume=False)

            self.assertEqual(states.CLEANWAIT, return_value)
            execute_mock.assert_called_once_with(task, self.clean_step)
            exp_target_raid_config = {
                "logical_disks": [
                    {'size_gb': 200, 'raid_level': 5}
                ]}
            self.assertEqual(
                exp_target_raid_config,
                task.node.driver_internal_info['target_raid_config'])

    @mock.patch.object(deploy_utils, 'agent_execute_clean_step',
                       autospec=True)
    def test_create_configuration_skip_nonroot(self, execute_mock):
        with task_manager.acquire(self.context, self.node.uuid) as task:
            execute_mock.return_value = states.CLEANWAIT

            return_value = task.driver.raid.create_configuration(
                task, create_nonroot_volumes=False)

            self.assertEqual(states.CLEANWAIT, return_value)
            execute_mock.assert_called_once_with(task, self.clean_step)
            exp_target_raid_config = {
                "logical_disks": [
                    {'size_gb': 200, 'raid_level': 0, 'is_root_volume': True},
                ]}
            self.assertEqual(
                exp_target_raid_config,
                task.node.driver_internal_info['target_raid_config'])

    @mock.patch.object(deploy_utils, 'agent_execute_clean_step',
                       autospec=True)
    def test_create_configuration_no_target_raid_config_after_skipping(
            self, execute_mock):
        with task_manager.acquire(self.context, self.node.uuid) as task:
            self.assertRaises(
                exception.MissingParameterValue,
                task.driver.raid.create_configuration,
                task, create_root_volume=False,
                create_nonroot_volumes=False)

            self.assertFalse(execute_mock.called)

    @mock.patch.object(deploy_utils, 'agent_execute_clean_step',
                       autospec=True)
    def test_create_configuration_empty_target_raid_config(
            self, execute_mock):
        execute_mock.return_value = states.CLEANING
        self.node.target_raid_config = {}
        self.node.save()
        with task_manager.acquire(self.context, self.node.uuid) as task:
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
    def test__create_configuration_final_registered(
            self, update_raid_info_mock):
        self.node.clean_step = {'interface': 'raid',
                                'step': 'create_configuration'}
        command = {'command_result': {'clean_result': 'foo'}}
        create_hook = agent_base_vendor._get_post_clean_step_hook(self.node)
        with task_manager.acquire(self.context, self.node.uuid) as task:
            create_hook(task, command)
            update_raid_info_mock.assert_called_once_with(task.node, 'foo')

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

    @mock.patch.object(deploy_utils, 'agent_execute_clean_step',
                       autospec=True)
    def test_delete_configuration(self, execute_mock):
        execute_mock.return_value = states.CLEANING
        with task_manager.acquire(self.context, self.node.uuid) as task:
            return_value = task.driver.raid.delete_configuration(task)

            execute_mock.assert_called_once_with(task, self.clean_step)
            self.assertEqual(states.CLEANING, return_value)

    def test__delete_configuration_final(self):
        command = {'command_result': {'clean_result': 'foo'}}
        with task_manager.acquire(self.context, self.node.uuid) as task:
            task.node.raid_config = {'foo': 'bar'}
            raid_mgmt = agent.AgentRAID
            raid_mgmt._delete_configuration_final(task, command)

        self.node.refresh()
        self.assertEqual({}, self.node.raid_config)

    def test__delete_configuration_final_registered(
            self):
        self.node.clean_step = {'interface': 'raid',
                                'step': 'delete_configuration'}
        self.node.raid_config = {'foo': 'bar'}
        command = {'command_result': {'clean_result': 'foo'}}
        delete_hook = agent_base_vendor._get_post_clean_step_hook(self.node)
        with task_manager.acquire(self.context, self.node.uuid) as task:
            delete_hook(task, command)

        self.node.refresh()
        self.assertEqual({}, self.node.raid_config)
