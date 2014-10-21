# Copyright 2014 Hewlett-Packard Development Company, L.P.
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

"""Test class for common methods used by iLO modules."""

import tempfile

import mock
from oslo.config import cfg

from ironic.common import boot_devices
from ironic.common import images
from ironic.common import states
from ironic.common import swift
from ironic.common import utils
from ironic.conductor import task_manager
from ironic.conductor import utils as manager_utils
from ironic.drivers.modules import agent
from ironic.drivers.modules import deploy_utils
from ironic.drivers.modules.ilo import common as ilo_common
from ironic.drivers.modules.ilo import deploy as ilo_deploy
from ironic.drivers.modules import iscsi_deploy
from ironic.drivers.modules import pxe
from ironic.drivers import utils as driver_utils
from ironic.openstack.common import importutils
from ironic.tests.conductor import utils as mgr_utils
from ironic.tests.db import base as db_base
from ironic.tests.db import utils as db_utils
from ironic.tests.objects import utils as obj_utils

ilo_client = importutils.try_import('proliantutils.ilo.ribcl')


INFO_DICT = db_utils.get_test_ilo_info()
CONF = cfg.CONF


class IloDeployPrivateMethodsTestCase(db_base.DbTestCase):

    def setUp(self):
        super(IloDeployPrivateMethodsTestCase, self).setUp()
        mgr_utils.mock_the_extension_manager(driver="iscsi_ilo")
        self.node = obj_utils.create_test_node(self.context,
                driver='iscsi_ilo', driver_info=INFO_DICT)

    def test__get_boot_iso_object_name(self):
        boot_iso_actual = ilo_deploy._get_boot_iso_object_name(self.node)
        boot_iso_expected = "boot-%s" % self.node.uuid
        self.assertEqual(boot_iso_expected, boot_iso_actual)

    @mock.patch.object(images, 'get_glance_image_property')
    @mock.patch.object(ilo_deploy, '_parse_deploy_info')
    def test__get_boot_iso_glance_image(self, deploy_info_mock,
            image_prop_mock):
        deploy_info_mock.return_value = {'image_source': 'image-uuid'}
        image_prop_mock.return_value = 'boot-iso-uuid'

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            boot_iso_actual = ilo_deploy._get_boot_iso(task, 'root-uuid')
            deploy_info_mock.assert_called_once_with(task.node)
            image_prop_mock.assert_called_once_with(task.context, 'image-uuid',
                'boot_iso')
            boot_iso_expected = 'glance:boot-iso-uuid'
            self.assertEqual(boot_iso_expected, boot_iso_actual)

    @mock.patch.object(driver_utils, 'get_node_capability')
    @mock.patch.object(images, 'get_glance_image_property')
    @mock.patch.object(ilo_deploy, '_parse_deploy_info')
    def test__get_boot_iso_uefi_no_glance_image(self, deploy_info_mock,
            image_prop_mock, get_node_cap_mock):
        deploy_info_mock.return_value = {'image_source': 'image-uuid'}
        image_prop_mock.return_value = None
        get_node_cap_mock.return_value = 'uefi'

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            boot_iso_result = ilo_deploy._get_boot_iso(task, 'root-uuid')
            deploy_info_mock.assert_called_once_with(task.node)
            image_prop_mock.assert_called_once_with(task.context, 'image-uuid',
                'boot_iso')
            get_node_cap_mock.assert_called_once_with(task.node, 'boot_mode')
            self.assertIsNone(boot_iso_result)

    @mock.patch.object(tempfile, 'NamedTemporaryFile')
    @mock.patch.object(images, 'create_boot_iso')
    @mock.patch.object(swift, 'SwiftAPI')
    @mock.patch.object(ilo_deploy, '_get_boot_iso_object_name')
    @mock.patch.object(images, 'get_glance_image_property')
    @mock.patch.object(ilo_deploy, '_parse_deploy_info')
    def test__get_boot_iso_create(self, deploy_info_mock, image_prop_mock,
                                  boot_object_name_mock, swift_api_mock,
                                  create_boot_iso_mock, tempfile_mock):
        CONF.keystone_authtoken.auth_uri = 'http://authurl'
        CONF.ilo.swift_ilo_container = 'ilo-cont'
        CONF.pxe.pxe_append_params = 'kernel-params'

        swift_obj_mock = swift_api_mock.return_value
        fileobj_mock = mock.MagicMock()
        fileobj_mock.name = 'tmpfile'
        mock_file_handle = mock.MagicMock(spec=file)
        mock_file_handle.__enter__.return_value = fileobj_mock
        tempfile_mock.return_value = mock_file_handle

        deploy_info_mock.return_value = {'image_source': 'image-uuid'}
        image_prop_mock.side_effect = [None, 'kernel-uuid', 'ramdisk-uuid']
        boot_object_name_mock.return_value = 'abcdef'
        create_boot_iso_mock.return_value = '/path/to/boot-iso'

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            boot_iso_actual = ilo_deploy._get_boot_iso(task, 'root-uuid')
            deploy_info_mock.assert_called_once_with(task.node)
            image_prop_mock.assert_any_call(task.context, 'image-uuid',
                'boot_iso')
            image_prop_mock.assert_any_call(task.context, 'image-uuid',
                'kernel_id')
            image_prop_mock.assert_any_call(task.context, 'image-uuid',
                'ramdisk_id')
            boot_object_name_mock.assert_called_once_with(task.node)
            create_boot_iso_mock.assert_called_once_with(task.context,
                    'tmpfile', 'kernel-uuid', 'ramdisk-uuid',
                    'root-uuid', 'kernel-params')
            swift_obj_mock.create_object.assert_called_once_with('ilo-cont',
                                                                 'abcdef',
                                                                 'tmpfile')
            boot_iso_expected = 'swift:abcdef'
            self.assertEqual(boot_iso_expected, boot_iso_actual)

    @mock.patch.object(ilo_deploy, '_get_boot_iso_object_name')
    @mock.patch.object(swift, 'SwiftAPI')
    def test__clean_up_boot_iso_for_instance(self, swift_mock,
                                             boot_object_name_mock):
        swift_obj_mock = swift_mock.return_value
        CONF.ilo.swift_ilo_container = 'ilo-cont'
        boot_object_name_mock.return_value = 'boot-object'
        ilo_deploy._clean_up_boot_iso_for_instance(self.node)
        swift_obj_mock.delete_object.assert_called_once_with('ilo-cont',
                                                             'boot-object')

    def test__get_single_nic_with_vif_port_id(self):
        obj_utils.create_test_port(self.context, node_id=self.node.id,
                address='aa:bb:cc', uuid=utils.generate_uuid(),
                extra={'vif_port_id': 'test-vif-A'}, driver='iscsi_ilo')
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            address = ilo_deploy._get_single_nic_with_vif_port_id(task)
            self.assertEqual('aa:bb:cc', address)

    @mock.patch.object(deploy_utils, 'check_for_missing_params')
    def test__parse_driver_info(self, check_params_mock):
        self.node.driver_info['ilo_deploy_iso'] = 'deploy-iso-uuid'
        driver_info_expected = {'ilo_deploy_iso': 'deploy-iso-uuid'}
        driver_info_actual = ilo_deploy._parse_driver_info(self.node)
        error_msg = ("Error validating iLO virtual media deploy. Some"
                     " parameters were missing in node's driver_info")
        check_params_mock.assert_called_once_with(driver_info_expected,
                                                  error_msg)
        self.assertEqual(driver_info_expected, driver_info_actual)

    @mock.patch.object(ilo_deploy, '_parse_driver_info')
    @mock.patch.object(iscsi_deploy, 'parse_instance_info')
    def test__parse_deploy_info(self, instance_info_mock, driver_info_mock):
        instance_info_mock.return_value = {'a': 'b'}
        driver_info_mock.return_value = {'c': 'd'}
        expected_info = {'a': 'b', 'c': 'd'}
        actual_info = ilo_deploy._parse_deploy_info(self.node)
        self.assertEqual(expected_info, actual_info)

    @mock.patch.object(manager_utils, 'node_power_action')
    @mock.patch.object(manager_utils, 'node_set_boot_device')
    @mock.patch.object(ilo_common, 'setup_vmedia_for_boot')
    def test__reboot_into(self, setup_vmedia_mock, set_boot_device_mock,
                          node_power_action_mock):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            opts = {'a': 'b'}
            ilo_deploy._reboot_into(task, 'iso', opts)
            setup_vmedia_mock.assert_called_once_with(task, 'iso', opts)
            set_boot_device_mock.assert_called_once_with(task,
                                                         boot_devices.CDROM)
            node_power_action_mock.assert_called_once_with(task, states.REBOOT)


class IloVirtualMediaIscsiDeployTestCase(db_base.DbTestCase):

    def setUp(self):
        super(IloVirtualMediaIscsiDeployTestCase, self).setUp()
        mgr_utils.mock_the_extension_manager(driver="iscsi_ilo")
        self.node = obj_utils.create_test_node(self.context,
                driver='iscsi_ilo', driver_info=INFO_DICT)

    @mock.patch.object(driver_utils, 'validate_boot_mode_capability')
    @mock.patch.object(iscsi_deploy, 'validate_glance_image_properties')
    @mock.patch.object(ilo_deploy, '_parse_deploy_info')
    @mock.patch.object(iscsi_deploy, 'validate')
    def test_validate(self, validate_mock, deploy_info_mock,
                      validate_prop_mock, validate_boot_mode_mock):
        d_info = {'a': 'b'}
        deploy_info_mock.return_value = d_info
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.driver.deploy.validate(task)
            validate_mock.assert_called_once_with(task)
            deploy_info_mock.assert_called_once_with(task.node)
            validate_prop_mock.assert_called_once_with(task.context,
                    d_info, ['kernel_id', 'ramdisk_id'])
            validate_boot_mode_mock.assert_called_once_with(task.node)

    @mock.patch.object(ilo_deploy, '_reboot_into')
    @mock.patch.object(ilo_deploy, '_get_single_nic_with_vif_port_id')
    @mock.patch.object(iscsi_deploy, 'build_deploy_ramdisk_options')
    @mock.patch.object(manager_utils, 'node_power_action')
    @mock.patch.object(iscsi_deploy, 'check_image_size')
    @mock.patch.object(iscsi_deploy, 'cache_instance_image')
    def test_deploy(self, cache_instance_image_mock, check_image_size_mock,
                    node_power_action_mock, build_opts_mock, get_nic_mock,
                    reboot_into_mock):
        deploy_opts = {'a': 'b'}
        build_opts_mock.return_value = deploy_opts
        get_nic_mock.return_value = '12:34:56:78:90:ab'
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:

            task.node.driver_info['ilo_deploy_iso'] = 'deploy-iso'
            returned_state = task.driver.deploy.deploy(task)

            node_power_action_mock.assert_any_call(task, states.POWER_OFF)
            cache_instance_image_mock.assert_called_once_with(task.context,
                    task.node)
            check_image_size_mock.assert_called_once_with(task)
            expected_ramdisk_opts = {'a': 'b', 'BOOTIF': '12:34:56:78:90:ab'}
            build_opts_mock.assert_called_once_with(task.node)
            get_nic_mock.assert_called_once_with(task)
            reboot_into_mock.assert_called_once_with(task, 'glance:deploy-iso',
                                                     expected_ramdisk_opts)

        self.assertEqual(states.DEPLOYWAIT, returned_state)

    @mock.patch.object(manager_utils, 'node_power_action')
    def test_tear_down(self, node_power_action_mock):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            returned_state = task.driver.deploy.tear_down(task)
            node_power_action_mock.assert_called_once_with(task,
                    states.POWER_OFF)
            self.assertEqual(states.DELETED, returned_state)

    @mock.patch.object(ilo_deploy, '_clean_up_boot_iso_for_instance')
    @mock.patch.object(iscsi_deploy, 'destroy_images')
    def test_clean_up(self, destroy_images_mock, clean_up_boot_mock):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.driver.deploy.clean_up(task)
            destroy_images_mock.assert_called_once_with(task.node.uuid)
            clean_up_boot_mock.assert_called_once_with(task.node)


class IloVirtualMediaAgentDeployTestCase(db_base.DbTestCase):

    def setUp(self):
        super(IloVirtualMediaAgentDeployTestCase, self).setUp()
        mgr_utils.mock_the_extension_manager(driver="agent_ilo")
        self.node = obj_utils.create_test_node(self.context,
                driver='agent_ilo', driver_info=INFO_DICT)

    @mock.patch.object(ilo_deploy, '_parse_driver_info')
    def test_validate(self, parse_driver_info_mock):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.driver.deploy.validate(task)
            parse_driver_info_mock.assert_called_once_with(task.node)

    @mock.patch.object(ilo_deploy, '_reboot_into')
    @mock.patch.object(agent, 'build_agent_options')
    def test_deploy(self, build_options_mock, reboot_into_mock):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            deploy_opts = {'a': 'b'}
            build_options_mock.return_value = deploy_opts
            task.node.driver_info['ilo_deploy_iso'] = 'deploy-iso-uuid'

            returned_state = task.driver.deploy.deploy(task)

            build_options_mock.assert_called_once_with(task.node)
            reboot_into_mock.assert_called_once_with(task,
                                                     'glance:deploy-iso-uuid',
                                                     deploy_opts)
            self.assertEqual(states.DEPLOYWAIT, returned_state)

    @mock.patch.object(manager_utils, 'node_power_action')
    def test_tear_down(self, node_power_action_mock):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            returned_state = task.driver.deploy.tear_down(task)
            node_power_action_mock.assert_called_once_with(task,
                    states.POWER_OFF)
            self.assertEqual(states.DELETED, returned_state)

    @mock.patch.object(agent, 'build_instance_info_for_deploy')
    def test_prepare(self, build_instance_info_mock):
        deploy_opts = {'a': 'b'}
        build_instance_info_mock.return_value = deploy_opts
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.driver.deploy.prepare(task)
            self.assertEqual(deploy_opts, task.node.instance_info)


class VendorPassthruTestCase(db_base.DbTestCase):

    def setUp(self):
        super(VendorPassthruTestCase, self).setUp()
        mgr_utils.mock_the_extension_manager(driver="iscsi_ilo")
        self.node = obj_utils.create_test_node(self.context,
                driver='iscsi_ilo', driver_info=INFO_DICT)

    @mock.patch.object(deploy_utils, 'notify_deploy_complete')
    @mock.patch.object(manager_utils, 'node_set_boot_device')
    @mock.patch.object(ilo_common, 'setup_vmedia_for_boot')
    @mock.patch.object(ilo_deploy, '_get_boot_iso')
    @mock.patch.object(iscsi_deploy, 'continue_deploy')
    @mock.patch.object(ilo_common, 'cleanup_vmedia_boot')
    def test__continue_deploy_good(self, cleanup_vmedia_boot_mock,
                                   continue_deploy_mock, get_boot_iso_mock,
                                   setup_vmedia_mock, set_boot_device_mock,
                                   notify_deploy_complete_mock):
        kwargs = {'method': 'pass_deploy_info', 'address': '123456'}
        continue_deploy_mock.return_value = 'root-uuid'
        get_boot_iso_mock.return_value = 'boot-iso'

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.node.provision_state = states.DEPLOYWAIT
            vendor = ilo_deploy.VendorPassthru()
            vendor._continue_deploy(task, **kwargs)

            cleanup_vmedia_boot_mock.assert_called_once_with(task)
            continue_deploy_mock.assert_called_once_with(task, **kwargs)
            get_boot_iso_mock.assert_called_once_with(task, 'root-uuid')
            setup_vmedia_mock.assert_called_once_with(task, 'boot-iso')
            set_boot_device_mock.assert_called_once_with(task,
                                                         boot_devices.CDROM)
            self.assertEqual('boot-iso',
                             task.node.instance_info['ilo_boot_iso'])
        notify_deploy_complete_mock.assert_called_once_with('123456')

    @mock.patch.object(ilo_deploy, 'LOG')
    def test__continue_deploy_bad(self, log_mock):
        kwargs = {'method': 'pass_deploy_info', 'address': '123456'}

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.node.provision_state = states.NOSTATE
            vendor = ilo_deploy.VendorPassthru()
            vendor._continue_deploy(task, **kwargs)

            self.assertTrue(log_mock.error.called)

    @mock.patch.object(iscsi_deploy, 'continue_deploy')
    @mock.patch.object(ilo_common, 'cleanup_vmedia_boot')
    def test__continue_deploy_deploy_no_boot_media(self,
            cleanup_vmedia_boot_mock, continue_deploy_mock):
        kwargs = {'method': 'pass_deploy_info', 'address': '123456'}
        continue_deploy_mock.return_value = None

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.node.provision_state = states.DEPLOYWAIT
            vendor = ilo_deploy.VendorPassthru()
            vendor._continue_deploy(task, **kwargs)

            cleanup_vmedia_boot_mock.assert_called_once_with(task)
            continue_deploy_mock.assert_called_once_with(task, **kwargs)


class IloPXEDeployTestCase(db_base.DbTestCase):

    def setUp(self):
        super(IloPXEDeployTestCase, self).setUp()
        mgr_utils.mock_the_extension_manager(driver="pxe_ilo")
        self.node = obj_utils.create_test_node(self.context,
                driver='pxe_ilo', driver_info=INFO_DICT)

    @mock.patch.object(pxe.PXEDeploy, 'validate')
    @mock.patch.object(driver_utils, 'validate_boot_mode_capability')
    def test_validate(self, boot_mode_mock, pxe_validate_mock):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.driver.deploy.validate(task)
            boot_mode_mock.assert_called_once_with(task.node)
            pxe_validate_mock.assert_called_once_with(task)

    @mock.patch.object(pxe.PXEDeploy, 'prepare')
    @mock.patch.object(ilo_common, 'set_boot_mode')
    @mock.patch.object(driver_utils, 'get_node_capability')
    def test_prepare(self, node_capability_mock,
                     set_boot_mode_mock, pxe_prepare_mock):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            node_capability_mock.return_value = 'uefi'
            task.driver.deploy.prepare(task)
            node_capability_mock.assert_called_once_with(task.node,
                                                         'boot_mode')
            set_boot_mode_mock.assert_called_once_with(task.node, 'uefi')
            pxe_prepare_mock.assert_called_once_with(task)

    @mock.patch.object(pxe.PXEDeploy, 'prepare')
    @mock.patch.object(ilo_common, 'update_boot_mode_capability')
    @mock.patch.object(driver_utils, 'get_node_capability')
    def test_prepare_boot_mode_doesnt_exist(self, node_capability_mock,
                                            update_capability_mock,
                                            pxe_prepare_mock):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            node_capability_mock.return_value = None
            task.driver.deploy.prepare(task)
            update_capability_mock.assert_called_once_with(task)
            pxe_prepare_mock.assert_called_once_with(task)

    @mock.patch.object(pxe.PXEDeploy, 'deploy')
    @mock.patch.object(manager_utils, 'node_set_boot_device')
    def test_deploy_boot_mode_exists(self, set_persistent_mock,
                                     pxe_deploy_mock):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.driver.deploy.deploy(task)
            set_persistent_mock.assert_called_with(task, boot_devices.PXE)
            pxe_deploy_mock.assert_called_once_with(task)


class IloPXEVendorPassthruTestCase(db_base.DbTestCase):

    def setUp(self):
        super(IloPXEVendorPassthruTestCase, self).setUp()
        mgr_utils.mock_the_extension_manager(driver="pxe_ilo")
        self.node = obj_utils.create_test_node(self.context,
                driver='pxe_ilo', driver_info=INFO_DICT)

    def test_vendor_routes(self):
        expected = ['pass_deploy_info']
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            vendor_routes = task.driver.vendor.vendor_routes
            self.assertIsInstance(vendor_routes, dict)
            self.assertEqual(expected, list(vendor_routes))

    def test_driver_routes(self):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            driver_routes = task.driver.vendor.driver_routes
            self.assertIsInstance(driver_routes, dict)
            self.assertEqual({}, driver_routes)

    @mock.patch.object(pxe.VendorPassthru, '_continue_deploy')
    @mock.patch.object(manager_utils, 'node_set_boot_device')
    def test_vendorpassthru(self, set_boot_device_mock,
                            pxe_vendorpassthru_mock):
        kwargs = {'address': '123456'}
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.node.provision_state = states.DEPLOYWAIT
            task.driver.vendor._continue_deploy(task, **kwargs)
            set_boot_device_mock.assert_called_with(task, boot_devices.PXE,
                                                    True)
            pxe_vendorpassthru_mock.assert_called_once_with(task, **kwargs)
