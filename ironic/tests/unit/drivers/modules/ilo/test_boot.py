# Copyright 2015 Hewlett-Packard Development Company, L.P.
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

"""Test class for boot methods used by iLO modules."""

import io
import tempfile

from ironic_lib import utils as ironic_utils
import mock
from oslo_config import cfg

from ironic.common import boot_devices
from ironic.common import exception
from ironic.common.glance_service import service_utils
from ironic.common import image_service
from ironic.common import images
from ironic.common import states
from ironic.common import swift
from ironic.conductor import task_manager
from ironic.conductor import utils as manager_utils
from ironic.drivers.modules import boot_mode_utils
from ironic.drivers.modules import deploy_utils
from ironic.drivers.modules.ilo import boot as ilo_boot
from ironic.drivers.modules.ilo import common as ilo_common
from ironic.drivers.modules.ilo import management as ilo_management
from ironic.drivers.modules import ipxe
from ironic.drivers.modules import pxe
from ironic.drivers.modules.storage import noop as noop_storage
from ironic.drivers import utils as driver_utils
from ironic.tests.unit.drivers.modules.ilo import test_common


CONF = cfg.CONF


class IloBootCommonMethodsTestCase(test_common.BaseIloTest):

    boot_interface = 'ilo-virtual-media'

    def test_parse_driver_info(self):
        self.node.driver_info['ilo_deploy_iso'] = 'deploy-iso'
        expected_driver_info = {'ilo_deploy_iso': 'deploy-iso'}

        actual_driver_info = ilo_boot.parse_driver_info(self.node)
        self.assertEqual(expected_driver_info, actual_driver_info)

    def test_parse_driver_info_exc(self):
        self.assertRaises(exception.MissingParameterValue,
                          ilo_boot.parse_driver_info, self.node)


class IloBootPrivateMethodsTestCase(test_common.BaseIloTest):

    boot_interface = 'ilo-virtual-media'

    def test__get_boot_iso_object_name(self):
        boot_iso_actual = ilo_boot._get_boot_iso_object_name(self.node)
        boot_iso_expected = "boot-%s" % self.node.uuid
        self.assertEqual(boot_iso_expected, boot_iso_actual)

    @mock.patch.object(image_service.HttpImageService, 'validate_href',
                       spec_set=True, autospec=True)
    def test__get_boot_iso_http_url(self, service_mock):
        url = 'http://abc.org/image/qcow2'
        i_info = self.node.instance_info
        i_info['ilo_boot_iso'] = url
        self.node.instance_info = i_info
        self.node.save()

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            boot_iso_actual = ilo_boot._get_boot_iso(task, 'root-uuid')
            service_mock.assert_called_once_with(mock.ANY, url)
            self.assertEqual(url, boot_iso_actual)

    @mock.patch.object(image_service.HttpImageService, 'validate_href',
                       spec_set=True, autospec=True)
    def test__get_boot_iso_unsupported_url(self, validate_href_mock):
        validate_href_mock.side_effect = exception.ImageRefValidationFailed(
            image_href='file://img.qcow2', reason='fail')
        url = 'file://img.qcow2'
        i_info = self.node.instance_info
        i_info['ilo_boot_iso'] = url
        self.node.instance_info = i_info
        self.node.save()

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            self.assertRaises(exception.ImageRefValidationFailed,
                              ilo_boot._get_boot_iso, task, 'root-uuid')

    @mock.patch.object(images, 'get_image_properties', spec_set=True,
                       autospec=True)
    @mock.patch.object(ilo_boot, '_parse_deploy_info', spec_set=True,
                       autospec=True)
    def test__get_boot_iso_glance_image(self, deploy_info_mock,
                                        image_props_mock):
        deploy_info_mock.return_value = {'image_source': 'image-uuid',
                                         'ilo_deploy_iso': 'deploy_iso_uuid'}
        image_props_mock.return_value = {'boot_iso': u'glance://uui\u0111',
                                         'kernel_id': None,
                                         'ramdisk_id': None}

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            driver_internal_info = task.node.driver_internal_info
            driver_internal_info['boot_iso_created_in_web_server'] = False
            task.node.driver_internal_info = driver_internal_info
            task.node.save()
            boot_iso_actual = ilo_boot._get_boot_iso(task, 'root-uuid')
            deploy_info_mock.assert_called_once_with(task.node)
            image_props_mock.assert_called_once_with(
                task.context, 'image-uuid',
                ['boot_iso', 'kernel_id', 'ramdisk_id'])
            boot_iso_expected = u'glance://uui\u0111'
            self.assertEqual(boot_iso_expected, boot_iso_actual)

    @mock.patch.object(boot_mode_utils, 'get_boot_mode_for_deploy',
                       spec_set=True, autospec=True)
    @mock.patch.object(ilo_boot.LOG, 'error', spec_set=True, autospec=True)
    @mock.patch.object(images, 'get_image_properties', spec_set=True,
                       autospec=True)
    @mock.patch.object(ilo_boot, '_parse_deploy_info', spec_set=True,
                       autospec=True)
    def test__get_boot_iso_uefi_no_glance_image(self,
                                                deploy_info_mock,
                                                image_props_mock,
                                                log_mock,
                                                boot_mode_mock):
        deploy_info_mock.return_value = {'image_source': 'image-uuid',
                                         'ilo_deploy_iso': 'deploy_iso_uuid'}
        image_props_mock.return_value = {'boot_iso': None,
                                         'kernel_id': None,
                                         'ramdisk_id': None}
        properties = {'capabilities': 'boot_mode:uefi'}

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.node.properties = properties
            boot_iso_result = ilo_boot._get_boot_iso(task, 'root-uuid')
            deploy_info_mock.assert_called_once_with(task.node)
            image_props_mock.assert_called_once_with(
                task.context, 'image-uuid',
                ['boot_iso', 'kernel_id', 'ramdisk_id'])
            self.assertTrue(log_mock.called)
            self.assertFalse(boot_mode_mock.called)
            self.assertIsNone(boot_iso_result)

    @mock.patch.object(tempfile, 'NamedTemporaryFile', spec_set=True,
                       autospec=True)
    @mock.patch.object(images, 'create_boot_iso', spec_set=True, autospec=True)
    @mock.patch.object(swift, 'SwiftAPI', spec_set=True, autospec=True)
    @mock.patch.object(ilo_boot, '_get_boot_iso_object_name', spec_set=True,
                       autospec=True)
    @mock.patch.object(driver_utils, 'get_node_capability', spec_set=True,
                       autospec=True)
    @mock.patch.object(images, 'get_image_properties', spec_set=True,
                       autospec=True)
    @mock.patch.object(ilo_boot, '_parse_deploy_info', spec_set=True,
                       autospec=True)
    def test__get_boot_iso_create(self, deploy_info_mock, image_props_mock,
                                  capability_mock, boot_object_name_mock,
                                  swift_api_mock,
                                  create_boot_iso_mock, tempfile_mock):
        CONF.ilo.swift_ilo_container = 'ilo-cont'
        CONF.pxe.pxe_append_params = 'kernel-params'

        swift_obj_mock = swift_api_mock.return_value
        fileobj_mock = mock.MagicMock(spec=io.BytesIO)
        fileobj_mock.name = 'tmpfile'
        mock_file_handle = mock.MagicMock(spec=io.BytesIO)
        mock_file_handle.__enter__.return_value = fileobj_mock
        tempfile_mock.return_value = mock_file_handle

        deploy_info_mock.return_value = {'image_source': 'image-uuid',
                                         'ilo_deploy_iso': 'deploy_iso_uuid'}
        image_props_mock.return_value = {'boot_iso': None,
                                         'kernel_id': 'kernel_uuid',
                                         'ramdisk_id': 'ramdisk_uuid'}
        boot_object_name_mock.return_value = 'abcdef'
        create_boot_iso_mock.return_value = '/path/to/boot-iso'
        capability_mock.return_value = 'uefi'
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            boot_iso_actual = ilo_boot._get_boot_iso(task, 'root-uuid')
            deploy_info_mock.assert_called_once_with(task.node)
            image_props_mock.assert_called_once_with(
                task.context, 'image-uuid',
                ['boot_iso', 'kernel_id', 'ramdisk_id'])
            boot_object_name_mock.assert_called_once_with(task.node)
            create_boot_iso_mock.assert_called_once_with(
                task.context, 'tmpfile', 'kernel_uuid', 'ramdisk_uuid',
                deploy_iso_href='deploy_iso_uuid',
                root_uuid='root-uuid',
                kernel_params='kernel-params',
                boot_mode='uefi')
            swift_obj_mock.create_object.assert_called_once_with('ilo-cont',
                                                                 'abcdef',
                                                                 'tmpfile')
            boot_iso_expected = 'swift:abcdef'
            self.assertEqual(boot_iso_expected, boot_iso_actual)

    @mock.patch.object(ilo_common, 'copy_image_to_web_server', spec_set=True,
                       autospec=True)
    @mock.patch.object(tempfile, 'NamedTemporaryFile', spec_set=True,
                       autospec=True)
    @mock.patch.object(images, 'create_boot_iso', spec_set=True, autospec=True)
    @mock.patch.object(ilo_boot, '_get_boot_iso_object_name', spec_set=True,
                       autospec=True)
    @mock.patch.object(driver_utils, 'get_node_capability', spec_set=True,
                       autospec=True)
    @mock.patch.object(images, 'get_image_properties', spec_set=True,
                       autospec=True)
    @mock.patch.object(ilo_boot, '_parse_deploy_info', spec_set=True,
                       autospec=True)
    def test__get_boot_iso_recreate_boot_iso_use_webserver(
            self, deploy_info_mock, image_props_mock,
            capability_mock, boot_object_name_mock,
            create_boot_iso_mock, tempfile_mock,
            copy_file_mock):
        CONF.ilo.swift_ilo_container = 'ilo-cont'
        CONF.ilo.use_web_server_for_images = True
        CONF.deploy.http_url = "http://10.10.1.30/httpboot"
        CONF.deploy.http_root = "/httpboot"
        CONF.pxe.pxe_append_params = 'kernel-params'

        fileobj_mock = mock.MagicMock(spec=io.BytesIO)
        fileobj_mock.name = 'tmpfile'
        mock_file_handle = mock.MagicMock(spec=io.BytesIO)
        mock_file_handle.__enter__.return_value = fileobj_mock
        tempfile_mock.return_value = mock_file_handle

        ramdisk_href = "http://10.10.1.30/httpboot/ramdisk"
        kernel_href = "http://10.10.1.30/httpboot/kernel"
        deploy_info_mock.return_value = {'image_source': 'image-uuid',
                                         'ilo_deploy_iso': 'deploy_iso_uuid'}
        image_props_mock.return_value = {'boot_iso': None,
                                         'kernel_id': kernel_href,
                                         'ramdisk_id': ramdisk_href}
        boot_object_name_mock.return_value = 'new_boot_iso'
        create_boot_iso_mock.return_value = '/path/to/boot-iso'
        capability_mock.return_value = 'uefi'
        copy_file_mock.return_value = "http://10.10.1.30/httpboot/new_boot_iso"

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            driver_internal_info = task.node.driver_internal_info
            driver_internal_info['boot_iso_created_in_web_server'] = True
            instance_info = task.node.instance_info
            old_boot_iso = 'http://10.10.1.30/httpboot/old_boot_iso'
            instance_info['ilo_boot_iso'] = old_boot_iso
            boot_iso_actual = ilo_boot._get_boot_iso(task, 'root-uuid')
            deploy_info_mock.assert_called_once_with(task.node)
            image_props_mock.assert_called_once_with(
                task.context, 'image-uuid',
                ['boot_iso', 'kernel_id', 'ramdisk_id'])
            boot_object_name_mock.assert_called_once_with(task.node)
            create_boot_iso_mock.assert_called_once_with(
                task.context, 'tmpfile', kernel_href, ramdisk_href,
                deploy_iso_href='deploy_iso_uuid',
                root_uuid='root-uuid',
                kernel_params='kernel-params',
                boot_mode='uefi')
            boot_iso_expected = 'http://10.10.1.30/httpboot/new_boot_iso'
            self.assertEqual(boot_iso_expected, boot_iso_actual)
            copy_file_mock.assert_called_once_with(fileobj_mock.name,
                                                   'new_boot_iso')

    @mock.patch.object(ilo_common, 'copy_image_to_web_server', spec_set=True,
                       autospec=True)
    @mock.patch.object(tempfile, 'NamedTemporaryFile', spec_set=True,
                       autospec=True)
    @mock.patch.object(images, 'create_boot_iso', spec_set=True, autospec=True)
    @mock.patch.object(ilo_boot, '_get_boot_iso_object_name', spec_set=True,
                       autospec=True)
    @mock.patch.object(driver_utils, 'get_node_capability', spec_set=True,
                       autospec=True)
    @mock.patch.object(images, 'get_image_properties', spec_set=True,
                       autospec=True)
    @mock.patch.object(ilo_boot, '_parse_deploy_info', spec_set=True,
                       autospec=True)
    def test__get_boot_iso_create_use_webserver_true_ramdisk_webserver(
            self, deploy_info_mock, image_props_mock,
            capability_mock, boot_object_name_mock,
            create_boot_iso_mock, tempfile_mock,
            copy_file_mock):
        CONF.ilo.swift_ilo_container = 'ilo-cont'
        CONF.ilo.use_web_server_for_images = True
        CONF.deploy.http_url = "http://10.10.1.30/httpboot"
        CONF.deploy.http_root = "/httpboot"
        CONF.pxe.pxe_append_params = 'kernel-params'

        fileobj_mock = mock.MagicMock(spec=io.BytesIO)
        fileobj_mock.name = 'tmpfile'
        mock_file_handle = mock.MagicMock(spec=io.BytesIO)
        mock_file_handle.__enter__.return_value = fileobj_mock
        tempfile_mock.return_value = mock_file_handle

        ramdisk_href = "http://10.10.1.30/httpboot/ramdisk"
        kernel_href = "http://10.10.1.30/httpboot/kernel"
        deploy_info_mock.return_value = {'image_source': 'image-uuid',
                                         'ilo_deploy_iso': 'deploy_iso_uuid'}
        image_props_mock.return_value = {'boot_iso': None,
                                         'kernel_id': kernel_href,
                                         'ramdisk_id': ramdisk_href}
        boot_object_name_mock.return_value = 'abcdef'
        create_boot_iso_mock.return_value = '/path/to/boot-iso'
        capability_mock.return_value = 'uefi'
        copy_file_mock.return_value = "http://10.10.1.30/httpboot/abcdef"

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            boot_iso_actual = ilo_boot._get_boot_iso(task, 'root-uuid')
            deploy_info_mock.assert_called_once_with(task.node)
            image_props_mock.assert_called_once_with(
                task.context, 'image-uuid',
                ['boot_iso', 'kernel_id', 'ramdisk_id'])
            boot_object_name_mock.assert_called_once_with(task.node)
            create_boot_iso_mock.assert_called_once_with(
                task.context, 'tmpfile', kernel_href, ramdisk_href,
                deploy_iso_href='deploy_iso_uuid',
                root_uuid='root-uuid',
                kernel_params='kernel-params',
                boot_mode='uefi')
            boot_iso_expected = 'http://10.10.1.30/httpboot/abcdef'
            self.assertEqual(boot_iso_expected, boot_iso_actual)
            copy_file_mock.assert_called_once_with(fileobj_mock.name,
                                                   'abcdef')

    @mock.patch.object(ilo_boot, '_get_boot_iso_object_name', spec_set=True,
                       autospec=True)
    @mock.patch.object(swift, 'SwiftAPI', spec_set=True, autospec=True)
    def test__clean_up_boot_iso_for_instance(self, swift_mock,
                                             boot_object_name_mock):
        swift_obj_mock = swift_mock.return_value
        CONF.ilo.swift_ilo_container = 'ilo-cont'
        boot_object_name_mock.return_value = 'boot-object'
        i_info = self.node.instance_info
        i_info['ilo_boot_iso'] = 'swift:bootiso'
        self.node.instance_info = i_info
        self.node.save()
        ilo_boot._clean_up_boot_iso_for_instance(self.node)
        swift_obj_mock.delete_object.assert_called_once_with('ilo-cont',
                                                             'boot-object')

    @mock.patch.object(ilo_boot.LOG, 'exception', spec_set=True,
                       autospec=True)
    @mock.patch.object(ilo_boot, '_get_boot_iso_object_name', spec_set=True,
                       autospec=True)
    @mock.patch.object(swift, 'SwiftAPI', spec_set=True, autospec=True)
    def test__clean_up_boot_iso_for_instance_exc(self, swift_mock,
                                                 boot_object_name_mock,
                                                 log_mock):
        swift_obj_mock = swift_mock.return_value
        exc = exception.SwiftObjectNotFoundError('error')
        swift_obj_mock.delete_object.side_effect = exc
        CONF.ilo.swift_ilo_container = 'ilo-cont'
        boot_object_name_mock.return_value = 'boot-object'
        i_info = self.node.instance_info
        i_info['ilo_boot_iso'] = 'swift:bootiso'
        self.node.instance_info = i_info
        self.node.save()
        ilo_boot._clean_up_boot_iso_for_instance(self.node)
        swift_obj_mock.delete_object.assert_called_once_with('ilo-cont',
                                                             'boot-object')
        self.assertTrue(log_mock.called)

    @mock.patch.object(ironic_utils, 'unlink_without_raise', spec_set=True,
                       autospec=True)
    def test__clean_up_boot_iso_for_instance_on_webserver(self, unlink_mock):

        CONF.ilo.use_web_server_for_images = True
        CONF.deploy.http_root = "/webserver"
        i_info = self.node.instance_info
        i_info['ilo_boot_iso'] = 'http://x.y.z.a/webserver/boot-object'
        self.node.instance_info = i_info
        self.node.save()
        boot_iso_path = "/webserver/boot-object"
        ilo_boot._clean_up_boot_iso_for_instance(self.node)
        unlink_mock.assert_called_once_with(boot_iso_path)

    @mock.patch.object(ilo_boot, '_get_boot_iso_object_name', spec_set=True,
                       autospec=True)
    def test__clean_up_boot_iso_for_instance_no_boot_iso(
            self, boot_object_name_mock):
        ilo_boot._clean_up_boot_iso_for_instance(self.node)
        self.assertFalse(boot_object_name_mock.called)

    @mock.patch.object(ilo_boot, 'parse_driver_info', spec_set=True,
                       autospec=True)
    @mock.patch.object(deploy_utils, 'get_image_instance_info',
                       spec_set=True, autospec=True)
    def test__parse_deploy_info(self, instance_info_mock, driver_info_mock):
        instance_info_mock.return_value = {'a': 'b'}
        driver_info_mock.return_value = {'c': 'd'}
        expected_info = {'a': 'b', 'c': 'd'}
        actual_info = ilo_boot._parse_deploy_info(self.node)
        self.assertEqual(expected_info, actual_info)

    @mock.patch.object(ilo_common, 'parse_driver_info', spec_set=True,
                       autospec=True)
    def test__validate_driver_info_MissingParam(self, mock_parse_driver_info):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            self.assertRaisesRegex(exception.MissingParameterValue,
                                   "Missing 'ilo_deploy_iso'",
                                   ilo_boot._validate_driver_info, task)
            mock_parse_driver_info.assert_called_once_with(task.node)

    @mock.patch.object(service_utils, 'is_glance_image', spec_set=True,
                       autospec=True)
    @mock.patch.object(ilo_common, 'parse_driver_info', spec_set=True,
                       autospec=True)
    def test__validate_driver_info_valid_uuid(self, mock_parse_driver_info,
                                              mock_is_glance_image):
        mock_is_glance_image.return_value = True
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            deploy_iso = '8a81759a-f29b-454b-8ab3-161c6ca1882c'
            task.node.driver_info['ilo_deploy_iso'] = deploy_iso
            ilo_boot._validate_driver_info(task)
            mock_parse_driver_info.assert_called_once_with(task.node)
            mock_is_glance_image.assert_called_once_with(deploy_iso)

    @mock.patch.object(image_service.HttpImageService, 'validate_href',
                       spec_set=True, autospec=True)
    @mock.patch.object(service_utils, 'is_glance_image', spec_set=True,
                       autospec=True)
    @mock.patch.object(ilo_common, 'parse_driver_info', spec_set=True,
                       autospec=True)
    def test__validate_driver_info_InvalidParam(self, mock_parse_driver_info,
                                                mock_is_glance_image,
                                                mock_validate_href):
        deploy_iso = 'http://abc.org/image/qcow2'
        mock_validate_href.side_effect = exception.ImageRefValidationFailed(
            image_href='http://abc.org/image/qcow2', reason='fail')
        mock_is_glance_image.return_value = False
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.node.driver_info['ilo_deploy_iso'] = deploy_iso
            self.assertRaisesRegex(exception.InvalidParameterValue,
                                   "Virtual media boot accepts",
                                   ilo_boot._validate_driver_info, task)
            mock_parse_driver_info.assert_called_once_with(task.node)
            mock_validate_href.assert_called_once_with(mock.ANY, deploy_iso)

    @mock.patch.object(image_service.HttpImageService, 'validate_href',
                       spec_set=True, autospec=True)
    @mock.patch.object(service_utils, 'is_glance_image', spec_set=True,
                       autospec=True)
    @mock.patch.object(ilo_common, 'parse_driver_info', spec_set=True,
                       autospec=True)
    def test__validate_driver_info_valid_url(self, mock_parse_driver_info,
                                             mock_is_glance_image,
                                             mock_validate_href):
        deploy_iso = 'http://abc.org/image/deploy.iso'
        mock_is_glance_image.return_value = False
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.node.driver_info['ilo_deploy_iso'] = deploy_iso
            ilo_boot._validate_driver_info(task)
            mock_parse_driver_info.assert_called_once_with(task.node)
            mock_validate_href.assert_called_once_with(mock.ANY, deploy_iso)

    @mock.patch.object(deploy_utils, 'validate_image_properties',
                       spec_set=True, autospec=True)
    @mock.patch.object(ilo_boot, '_parse_deploy_info', spec_set=True,
                       autospec=True)
    def _test__validate_instance_image_info(self,
                                            deploy_info_mock,
                                            validate_prop_mock,
                                            props_expected):
        d_info = {'image_source': 'uuid'}
        deploy_info_mock.return_value = d_info
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            ilo_boot._validate_instance_image_info(task)
            deploy_info_mock.assert_called_once_with(task.node)
            validate_prop_mock.assert_called_once_with(
                task.context, d_info, props_expected)

    @mock.patch.object(service_utils, 'is_glance_image', spec_set=True,
                       autospec=True)
    def test__validate_glance_partition_image(self,
                                              is_glance_image_mock):
        is_glance_image_mock.return_value = True
        self._test__validate_instance_image_info(props_expected=['kernel_id',
                                                                 'ramdisk_id'])

    def test__validate_whole_disk_image(self):
        self.node.driver_internal_info = {'is_whole_disk_image': True}
        self.node.save()
        self._test__validate_instance_image_info(props_expected=[])

    @mock.patch.object(service_utils, 'is_glance_image', spec_set=True,
                       autospec=True)
    def test__validate_non_glance_partition_image(self, is_glance_image_mock):
        is_glance_image_mock.return_value = False
        self._test__validate_instance_image_info(props_expected=['kernel',
                                                                 'ramdisk'])

    @mock.patch.object(ilo_common, 'set_secure_boot_mode', spec_set=True,
                       autospec=True)
    @mock.patch.object(ilo_common, 'get_secure_boot_mode', spec_set=True,
                       autospec=True)
    def test__disable_secure_boot_false(self,
                                        func_get_secure_boot_mode,
                                        func_set_secure_boot_mode):
        func_get_secure_boot_mode.return_value = False
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            returned_state = ilo_boot._disable_secure_boot(task)
            func_get_secure_boot_mode.assert_called_once_with(task)
            self.assertFalse(func_set_secure_boot_mode.called)
        self.assertFalse(returned_state)

    @mock.patch.object(ilo_common, 'set_secure_boot_mode', spec_set=True,
                       autospec=True)
    @mock.patch.object(ilo_common, 'get_secure_boot_mode', spec_set=True,
                       autospec=True)
    def test__disable_secure_boot_true(self,
                                       func_get_secure_boot_mode,
                                       func_set_secure_boot_mode):
        func_get_secure_boot_mode.return_value = True
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            returned_state = ilo_boot._disable_secure_boot(task)
            func_get_secure_boot_mode.assert_called_once_with(task)
            func_set_secure_boot_mode.assert_called_once_with(task, False)
        self.assertTrue(returned_state)

    @mock.patch.object(ilo_boot, 'exception', spec_set=True, autospec=True)
    @mock.patch.object(ilo_common, 'get_secure_boot_mode', spec_set=True,
                       autospec=True)
    def test__disable_secure_boot_exception(self,
                                            func_get_secure_boot_mode,
                                            exception_mock):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            exception_mock.IloOperationNotSupported = Exception
            func_get_secure_boot_mode.side_effect = Exception
            returned_state = ilo_boot._disable_secure_boot(task)
            func_get_secure_boot_mode.assert_called_once_with(task)
        self.assertFalse(returned_state)

    @mock.patch.object(ilo_common, 'update_boot_mode', spec_set=True,
                       autospec=True)
    @mock.patch.object(ilo_boot, '_disable_secure_boot', spec_set=True,
                       autospec=True)
    @mock.patch.object(manager_utils, 'node_power_action', spec_set=True,
                       autospec=True)
    def test_prepare_node_for_deploy(self,
                                     func_node_power_action,
                                     func_disable_secure_boot,
                                     func_update_boot_mode):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            func_disable_secure_boot.return_value = False
            ilo_boot.prepare_node_for_deploy(task)
            func_node_power_action.assert_called_once_with(task,
                                                           states.POWER_OFF)
            func_disable_secure_boot.assert_called_once_with(task)
            func_update_boot_mode.assert_called_once_with(task)
            bootmode = driver_utils.get_node_capability(task.node, "boot_mode")
            self.assertIsNone(bootmode)

    @mock.patch.object(ilo_common, 'update_boot_mode', spec_set=True,
                       autospec=True)
    @mock.patch.object(ilo_boot, '_disable_secure_boot', spec_set=True,
                       autospec=True)
    @mock.patch.object(manager_utils, 'node_power_action', spec_set=True,
                       autospec=True)
    def test_prepare_node_for_deploy_sec_boot_on(self,
                                                 func_node_power_action,
                                                 func_disable_secure_boot,
                                                 func_update_boot_mode):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            func_disable_secure_boot.return_value = True
            ilo_boot.prepare_node_for_deploy(task)
            func_node_power_action.assert_called_once_with(task,
                                                           states.POWER_OFF)
            func_disable_secure_boot.assert_called_once_with(task)
            self.assertFalse(func_update_boot_mode.called)
            ret_boot_mode = task.node.instance_info['deploy_boot_mode']
            self.assertEqual('uefi', ret_boot_mode)
            bootmode = driver_utils.get_node_capability(task.node, "boot_mode")
            self.assertIsNone(bootmode)

    @mock.patch.object(ilo_common, 'update_boot_mode', spec_set=True,
                       autospec=True)
    @mock.patch.object(ilo_boot, '_disable_secure_boot', spec_set=True,
                       autospec=True)
    @mock.patch.object(manager_utils, 'node_power_action', spec_set=True,
                       autospec=True)
    def test_prepare_node_for_deploy_inst_info(self,
                                               func_node_power_action,
                                               func_disable_secure_boot,
                                               func_update_boot_mode):
        instance_info = {'capabilities': '{"secure_boot": "true"}'}
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            func_disable_secure_boot.return_value = False
            task.node.instance_info = instance_info
            ilo_boot.prepare_node_for_deploy(task)
            func_node_power_action.assert_called_once_with(task,
                                                           states.POWER_OFF)
            func_disable_secure_boot.assert_called_once_with(task)
            func_update_boot_mode.assert_called_once_with(task)
            bootmode = driver_utils.get_node_capability(task.node, "boot_mode")
            self.assertIsNone(bootmode)
            self.assertNotIn('deploy_boot_mode', task.node.instance_info)

    @mock.patch.object(ilo_common, 'update_boot_mode', spec_set=True,
                       autospec=True)
    @mock.patch.object(ilo_boot, '_disable_secure_boot', spec_set=True,
                       autospec=True)
    @mock.patch.object(manager_utils, 'node_power_action', spec_set=True,
                       autospec=True)
    def test_prepare_node_for_deploy_sec_boot_on_inst_info(
            self, func_node_power_action, func_disable_secure_boot,
            func_update_boot_mode):
        instance_info = {'capabilities': '{"secure_boot": "true"}'}
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            func_disable_secure_boot.return_value = True
            task.node.instance_info = instance_info
            ilo_boot.prepare_node_for_deploy(task)
            func_node_power_action.assert_called_once_with(task,
                                                           states.POWER_OFF)
            func_disable_secure_boot.assert_called_once_with(task)
            self.assertFalse(func_update_boot_mode.called)
            bootmode = driver_utils.get_node_capability(task.node, "boot_mode")
            self.assertIsNone(bootmode)
            self.assertNotIn('deploy_boot_mode', task.node.instance_info)


class IloVirtualMediaBootTestCase(test_common.BaseIloTest):

    boot_interface = 'ilo-virtual-media'

    @mock.patch.object(noop_storage.NoopStorage, 'should_write_image',
                       autospec=True)
    @mock.patch.object(ilo_boot, '_validate_driver_info',
                       spec_set=True, autospec=True)
    @mock.patch.object(ilo_boot, '_validate_instance_image_info',
                       spec_set=True, autospec=True)
    def test_validate(self, mock_val_instance_image_info,
                      mock_val_driver_info, storage_mock):
        instance_info = self.node.instance_info
        instance_info['ilo_boot_iso'] = 'deploy-iso'
        instance_info['image_source'] = '6b2f0c0c-79e8-4db6-842e-43c9764204af'
        self.node.instance_info = instance_info
        self.node.save()
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:

            task.node.driver_info['ilo_deploy_iso'] = 'deploy-iso'
            storage_mock.return_value = True
            task.driver.boot.validate(task)
            mock_val_instance_image_info.assert_called_once_with(task)
            mock_val_driver_info.assert_called_once_with(task)

    @mock.patch.object(ilo_boot, '_validate_driver_info',
                       spec_set=True, autospec=True)
    @mock.patch.object(image_service.HttpImageService, 'validate_href',
                       spec_set=True, autospec=True)
    @mock.patch.object(service_utils, 'is_glance_image', spec_set=True,
                       autospec=True)
    def test_validate_ramdisk_boot_option_glance(self, is_glance_image_mock,
                                                 validate_href_mock,
                                                 val_driver_info_mock):
        instance_info = self.node.instance_info
        boot_iso = '6b2f0c0c-79e8-4db6-842e-43c9764204af'
        instance_info['ilo_boot_iso'] = boot_iso
        instance_info['capabilities'] = '{"boot_option": "ramdisk"}'
        self.node.instance_info = instance_info
        self.node.save()
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            is_glance_image_mock.return_value = True
            task.driver.boot.validate(task)
            is_glance_image_mock.assert_called_once_with(boot_iso)
            self.assertFalse(validate_href_mock.called)
            self.assertFalse(val_driver_info_mock.called)

    @mock.patch.object(ilo_boot, '_validate_driver_info',
                       spec_set=True, autospec=True)
    @mock.patch.object(image_service.HttpImageService, 'validate_href',
                       spec_set=True, autospec=True)
    @mock.patch.object(service_utils, 'is_glance_image', spec_set=True,
                       autospec=True)
    def test_validate_ramdisk_boot_option_webserver(self, is_glance_image_mock,
                                                    validate_href_mock,
                                                    val_driver_info_mock):
        instance_info = self.node.instance_info
        boot_iso = 'http://myserver/boot.iso'
        instance_info['ilo_boot_iso'] = boot_iso
        instance_info['capabilities'] = '{"boot_option": "ramdisk"}'
        self.node.instance_info = instance_info
        self.node.save()
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            is_glance_image_mock.return_value = False
            task.driver.boot.validate(task)
            is_glance_image_mock.assert_called_once_with(boot_iso)
            validate_href_mock.assert_called_once_with(mock.ANY, boot_iso)
            self.assertFalse(val_driver_info_mock.called)

    @mock.patch.object(ilo_boot.LOG, 'error', spec_set=True, autospec=True)
    @mock.patch.object(ilo_boot, '_validate_driver_info',
                       spec_set=True, autospec=True)
    @mock.patch.object(image_service.HttpImageService, 'validate_href',
                       spec_set=True, autospec=True)
    @mock.patch.object(service_utils, 'is_glance_image', spec_set=True,
                       autospec=True)
    def test_validate_ramdisk_boot_option_webserver_exc(self,
                                                        is_glance_image_mock,
                                                        validate_href_mock,
                                                        val_driver_info_mock,
                                                        log_mock):
        instance_info = self.node.instance_info
        validate_href_mock.side_effect = exception.ImageRefValidationFailed(
            image_href='http://myserver/boot.iso', reason='fail')
        boot_iso = 'http://myserver/boot.iso'
        instance_info['ilo_boot_iso'] = boot_iso
        instance_info['capabilities'] = '{"boot_option": "ramdisk"}'
        self.node.instance_info = instance_info
        self.node.save()
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:

            is_glance_image_mock.return_value = False
            self.assertRaisesRegex(exception.ImageRefValidationFailed,
                                   "Validation of image href "
                                   "http://myserver/boot.iso failed",
                                   task.driver.boot.validate, task)
            is_glance_image_mock.assert_called_once_with(boot_iso)
            validate_href_mock.assert_called_once_with(mock.ANY, boot_iso)
            self.assertFalse(val_driver_info_mock.called)
            self.assertIn("Virtual media deploy with 'ramdisk' boot_option "
                          "accepts only Glance images or HTTP(S) URLs as "
                          "instance_info['ilo_boot_iso'].",
                          log_mock.call_args[0][0])

    @mock.patch.object(noop_storage.NoopStorage, 'should_write_image',
                       autospec=True)
    @mock.patch.object(ilo_boot, '_validate_driver_info',
                       spec_set=True, autospec=True)
    @mock.patch.object(ilo_boot, '_validate_instance_image_info',
                       spec_set=True, autospec=True)
    def test_validate_boot_from_volume(self, mock_val_instance_image_info,
                                       mock_val_driver_info, storage_mock):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.node.driver_info['ilo_deploy_iso'] = 'deploy-iso'
            storage_mock.return_value = False
            task.driver.boot.validate(task)
            mock_val_driver_info.assert_called_once_with(task)
            self.assertFalse(mock_val_instance_image_info.called)

    @mock.patch.object(ilo_boot, '_validate_driver_info', autospec=True)
    def test_validate_inspection(self, mock_val_driver_info):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            task.node.driver_info['ilo_deploy_iso'] = 'deploy-iso'
            task.driver.boot.validate_inspection(task)
            mock_val_driver_info.assert_called_once_with(task)

    @mock.patch.object(ilo_common, 'parse_driver_info', spec_set=True,
                       autospec=True)
    def test_validate_inspection_missing(self, mock_parse_driver_info):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            self.assertRaises(exception.UnsupportedDriverExtension,
                              task.driver.boot.validate_inspection, task)

    @mock.patch.object(ilo_boot, 'prepare_node_for_deploy',
                       spec_set=True, autospec=True)
    @mock.patch.object(ilo_common, 'eject_vmedia_devices',
                       spec_set=True, autospec=True)
    @mock.patch.object(ilo_common, 'setup_vmedia', spec_set=True,
                       autospec=True)
    @mock.patch.object(deploy_utils, 'get_single_nic_with_vif_port_id',
                       spec_set=True, autospec=True)
    def _test_prepare_ramdisk(self, get_nic_mock, setup_vmedia_mock,
                              eject_mock,
                              prepare_node_for_deploy_mock,
                              ilo_boot_iso, image_source,
                              ramdisk_params={'a': 'b'},
                              mode='deploy'):
        instance_info = self.node.instance_info
        instance_info['ilo_boot_iso'] = ilo_boot_iso
        instance_info['image_source'] = image_source
        self.node.instance_info = instance_info
        self.node.save()
        iso = 'provisioning-iso'

        get_nic_mock.return_value = '12:34:56:78:90:ab'
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:

            driver_info = task.node.driver_info
            driver_info['ilo_%s_iso' % mode] = iso
            task.node.driver_info = driver_info

            task.driver.boot.prepare_ramdisk(task, ramdisk_params)

            prepare_node_for_deploy_mock.assert_called_once_with(task)
            eject_mock.assert_called_once_with(task)
            expected_ramdisk_opts = {'a': 'b', 'BOOTIF': '12:34:56:78:90:ab',
                                     'ipa-agent-token': mock.ANY}
            get_nic_mock.assert_called_once_with(task)
            setup_vmedia_mock.assert_called_once_with(task, iso,
                                                      expected_ramdisk_opts)

    @mock.patch.object(service_utils, 'is_glance_image', spec_set=True,
                       autospec=True)
    def test_prepare_ramdisk_in_takeover(self, mock_is_image):
        """Ensure deploy ops are blocked when not deploying and not cleaning"""

        for state in states.STABLE_STATES:
            mock_is_image.reset_mock()
            self.node.provision_state = state
            self.node.save()
            with task_manager.acquire(self.context, self.node.uuid,
                                      shared=False) as task:
                self.assertIsNone(
                    task.driver.boot.prepare_ramdisk(task, None))
                self.assertFalse(mock_is_image.called)

    def test_prepare_ramdisk_rescue_glance_image(self):
        self.node.provision_state = states.RESCUING
        self.node.save()
        self._test_prepare_ramdisk(
            ilo_boot_iso='swift:abcdef',
            image_source='6b2f0c0c-79e8-4db6-842e-43c9764204af',
            mode='rescue')
        self.node.refresh()
        self.assertNotIn('ilo_boot_iso', self.node.instance_info)

    def test_prepare_ramdisk_rescue_not_a_glance_image(self):
        self.node.provision_state = states.RESCUING
        self.node.save()
        self._test_prepare_ramdisk(
            ilo_boot_iso='http://mybootiso',
            image_source='http://myimage',
            mode='rescue')
        self.node.refresh()
        self.assertEqual('http://mybootiso',
                         self.node.instance_info['ilo_boot_iso'])

    def test_prepare_ramdisk_glance_image(self):
        self.node.provision_state = states.DEPLOYING
        self.node.save()
        self._test_prepare_ramdisk(
            ilo_boot_iso='swift:abcdef',
            image_source='6b2f0c0c-79e8-4db6-842e-43c9764204af')
        self.node.refresh()
        self.assertNotIn('ilo_boot_iso', self.node.instance_info)

    def test_prepare_ramdisk_not_a_glance_image(self):
        self.node.provision_state = states.DEPLOYING
        self.node.save()
        self._test_prepare_ramdisk(
            ilo_boot_iso='http://mybootiso',
            image_source='http://myimage')
        self.node.refresh()
        self.assertEqual('http://mybootiso',
                         self.node.instance_info['ilo_boot_iso'])

    def test_prepare_ramdisk_glance_image_cleaning(self):
        self.node.provision_state = states.CLEANING
        self.node.save()
        self._test_prepare_ramdisk(
            ilo_boot_iso='swift:abcdef',
            image_source='6b2f0c0c-79e8-4db6-842e-43c9764204af')
        self.node.refresh()
        self.assertNotIn('ilo_boot_iso', self.node.instance_info)

    def test_prepare_ramdisk_not_a_glance_image_cleaning(self):
        self.node.provision_state = states.CLEANING
        self.node.save()
        self._test_prepare_ramdisk(
            ilo_boot_iso='http://mybootiso',
            image_source='http://myimage')
        self.node.refresh()
        self.assertEqual('http://mybootiso',
                         self.node.instance_info['ilo_boot_iso'])

    @mock.patch.object(manager_utils, 'node_set_boot_device', spec_set=True,
                       autospec=True)
    @mock.patch.object(ilo_common, 'setup_vmedia_for_boot', spec_set=True,
                       autospec=True)
    @mock.patch.object(ilo_boot, '_get_boot_iso', spec_set=True,
                       autospec=True)
    def test__configure_vmedia_boot_with_boot_iso(
            self, get_boot_iso_mock, setup_vmedia_mock, set_boot_device_mock):
        root_uuid = {'root uuid': 'root_uuid'}

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            get_boot_iso_mock.return_value = 'boot.iso'

            task.driver.boot._configure_vmedia_boot(
                task, root_uuid)

            get_boot_iso_mock.assert_called_once_with(
                task, root_uuid)
            setup_vmedia_mock.assert_called_once_with(
                task, 'boot.iso')
            set_boot_device_mock.assert_called_once_with(
                task, boot_devices.CDROM, persistent=True)
            self.assertEqual('boot.iso',
                             task.node.instance_info['ilo_boot_iso'])

    @mock.patch.object(manager_utils, 'node_set_boot_device', spec_set=True,
                       autospec=True)
    @mock.patch.object(ilo_common, 'setup_vmedia_for_boot', spec_set=True,
                       autospec=True)
    @mock.patch.object(ilo_boot, '_get_boot_iso', spec_set=True,
                       autospec=True)
    def test__configure_vmedia_boot_without_boot_iso(
            self, get_boot_iso_mock, setup_vmedia_mock, set_boot_device_mock):
        root_uuid = {'root uuid': 'root_uuid'}

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            get_boot_iso_mock.return_value = None

            task.driver.boot._configure_vmedia_boot(
                task, root_uuid)

            get_boot_iso_mock.assert_called_once_with(
                task, root_uuid)
            self.assertFalse(setup_vmedia_mock.called)
            self.assertFalse(set_boot_device_mock.called)

    @mock.patch.object(deploy_utils, 'is_iscsi_boot',
                       spec_set=True, autospec=True)
    @mock.patch.object(ilo_common, 'update_secure_boot_mode', spec_set=True,
                       autospec=True)
    @mock.patch.object(manager_utils, 'node_power_action', spec_set=True,
                       autospec=True)
    @mock.patch.object(ilo_common, 'cleanup_vmedia_boot', spec_set=True,
                       autospec=True)
    @mock.patch.object(ilo_boot, '_clean_up_boot_iso_for_instance',
                       spec_set=True, autospec=True)
    def _test_clean_up_instance(self, cleanup_iso_mock,
                                cleanup_vmedia_mock, node_power_mock,
                                update_secure_boot_mode_mock,
                                is_iscsi_boot_mock):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            driver_internal_info = task.node.driver_internal_info
            driver_internal_info['boot_iso_created_in_web_server'] = False
            task.node.driver_internal_info = driver_internal_info
            task.node.save()
            is_iscsi_boot_mock.return_value = False
            task.driver.boot.clean_up_instance(task)
            cleanup_iso_mock.assert_called_once_with(task.node)
            cleanup_vmedia_mock.assert_called_once_with(task)
            driver_internal_info = task.node.driver_internal_info
            self.assertNotIn('boot_iso_created_in_web_server',
                             driver_internal_info)
            node_power_mock.assert_called_once_with(task,
                                                    states.POWER_OFF)
            update_secure_boot_mode_mock.assert_called_once_with(task, False)

    def test_clean_up_instance_deleting(self):
        self.node.provisioning_state = states.DELETING
        self._test_clean_up_instance()

    def test_clean_up_instance_rescuing(self):
        self.node.provisioning_state = states.RESCUING
        self._test_clean_up_instance()

    @mock.patch.object(deploy_utils, 'is_iscsi_boot',
                       spec_set=True, autospec=True)
    @mock.patch.object(ilo_management.IloManagement, 'clear_iscsi_boot_target',
                       spec_set=True, autospec=True)
    @mock.patch.object(ilo_common, 'update_secure_boot_mode', spec_set=True,
                       autospec=True)
    @mock.patch.object(manager_utils, 'node_power_action', spec_set=True,
                       autospec=True)
    def test_clean_up_instance_boot_from_volume(
            self, node_power_mock, update_secure_boot_mode_mock,
            clear_iscsi_boot_target_mock,
            is_iscsi_boot_mock):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            driver_internal_info = task.node.driver_internal_info
            driver_internal_info['ilo_uefi_iscsi_boot'] = True
            task.node.driver_internal_info = driver_internal_info
            task.node.save()
            is_iscsi_boot_mock.return_value = True
            task.driver.boot.clean_up_instance(task)
            node_power_mock.assert_called_once_with(task,
                                                    states.POWER_OFF)
            clear_iscsi_boot_target_mock.assert_called_once_with(mock.ANY,
                                                                 task)
            update_secure_boot_mode_mock.assert_called_once_with(task, False)
            self.assertIsNone(task.node.driver_internal_info.get(
                              'ilo_uefi_iscsi_boot'))

    @mock.patch.object(ilo_common, 'cleanup_vmedia_boot', spec_set=True,
                       autospec=True)
    @mock.patch.object(ilo_boot, '_clean_up_boot_iso_for_instance',
                       spec_set=True, autospec=True)
    @mock.patch.object(deploy_utils, 'is_iscsi_boot',
                       spec_set=True, autospec=True)
    @mock.patch.object(ilo_common, 'update_secure_boot_mode', spec_set=True,
                       autospec=True)
    @mock.patch.object(manager_utils, 'node_power_action', spec_set=True,
                       autospec=True)
    def test_clean_up_instance_boot_from_volume_bios(
            self, node_power_mock, update_secure_boot_mode_mock,
            is_iscsi_boot_mock, cleanup_iso_mock, cleanup_vmedia_mock):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            is_iscsi_boot_mock.return_value = False
            task.driver.boot.clean_up_instance(task)
            cleanup_iso_mock.assert_called_once_with(task.node)
            cleanup_vmedia_mock.assert_called_once_with(task)
            driver_internal_info = task.node.driver_internal_info
            self.assertNotIn('boot_iso_created_in_web_server',
                             driver_internal_info)
            node_power_mock.assert_called_once_with(task,
                                                    states.POWER_OFF)
            update_secure_boot_mode_mock.assert_called_once_with(task, False)

    @mock.patch.object(ilo_common, 'cleanup_vmedia_boot', spec_set=True,
                       autospec=True)
    def test_clean_up_ramdisk(self, cleanup_vmedia_mock):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.driver.boot.clean_up_ramdisk(task)
            cleanup_vmedia_mock.assert_called_once_with(task)

    @mock.patch.object(deploy_utils, 'is_iscsi_boot',
                       spec_set=True, autospec=True)
    @mock.patch.object(ilo_common, 'update_secure_boot_mode', spec_set=True,
                       autospec=True)
    @mock.patch.object(ilo_common, 'update_boot_mode', spec_set=True,
                       autospec=True)
    @mock.patch.object(manager_utils, 'node_set_boot_device', spec_set=True,
                       autospec=True)
    @mock.patch.object(ilo_common, 'cleanup_vmedia_boot', spec_set=True,
                       autospec=True)
    def _test_prepare_instance_whole_disk_image(
            self, cleanup_vmedia_boot_mock, set_boot_device_mock,
            update_boot_mode_mock, update_secure_boot_mode_mock,
            is_iscsi_boot_mock):
        self.node.driver_internal_info = {'is_whole_disk_image': True}
        self.node.save()
        is_iscsi_boot_mock.return_value = False
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.driver.boot.prepare_instance(task)

            cleanup_vmedia_boot_mock.assert_called_once_with(task)
            set_boot_device_mock.assert_called_once_with(task,
                                                         boot_devices.DISK,
                                                         persistent=True)
            update_boot_mode_mock.assert_called_once_with(task)
            update_secure_boot_mode_mock.assert_called_once_with(task, True)
            self.assertIsNone(task.node.driver_internal_info.get(
                              'ilo_uefi_iscsi_boot'))

    def test_prepare_instance_whole_disk_image_local(self):
        self.node.instance_info = {'capabilities': '{"boot_option": "local"}'}
        self.node.save()
        self._test_prepare_instance_whole_disk_image()

    def test_prepare_instance_whole_disk_image(self):
        self._test_prepare_instance_whole_disk_image()

    @mock.patch.object(deploy_utils, 'is_iscsi_boot',
                       spec_set=True, autospec=True)
    @mock.patch.object(ilo_common, 'update_secure_boot_mode', spec_set=True,
                       autospec=True)
    @mock.patch.object(ilo_common, 'update_boot_mode', spec_set=True,
                       autospec=True)
    @mock.patch.object(ilo_boot.IloVirtualMediaBoot,
                       '_configure_vmedia_boot', spec_set=True,
                       autospec=True)
    @mock.patch.object(ilo_common, 'cleanup_vmedia_boot', spec_set=True,
                       autospec=True)
    def test_prepare_instance_partition_image(
            self, cleanup_vmedia_boot_mock, configure_vmedia_mock,
            update_boot_mode_mock, update_secure_boot_mode_mock,
            is_iscsi_boot_mock):
        self.node.driver_internal_info = {'root_uuid_or_disk_id': (
            "12312642-09d3-467f-8e09-12385826a123")}
        self.node.save()
        is_iscsi_boot_mock.return_value = False
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.driver.boot.prepare_instance(task)
            cleanup_vmedia_boot_mock.assert_called_once_with(task)
            configure_vmedia_mock.assert_called_once_with(
                mock.ANY, task, "12312642-09d3-467f-8e09-12385826a123")
            update_boot_mode_mock.assert_called_once_with(task)
            update_secure_boot_mode_mock.assert_called_once_with(task, True)
            self.assertIsNone(task.node.driver_internal_info.get(
                              'ilo_uefi_iscsi_boot'))

    @mock.patch.object(ilo_common, 'cleanup_vmedia_boot', spec_set=True,
                       autospec=True)
    @mock.patch.object(deploy_utils, 'is_iscsi_boot',
                       spec_set=True, autospec=True)
    @mock.patch.object(boot_mode_utils, 'get_boot_mode_for_deploy',
                       spec_set=True, autospec=True)
    @mock.patch.object(ilo_management.IloManagement, 'set_iscsi_boot_target',
                       spec_set=True, autospec=True)
    @mock.patch.object(manager_utils, 'node_set_boot_device', spec_set=True,
                       autospec=True)
    @mock.patch.object(ilo_common, 'update_boot_mode', spec_set=True,
                       autospec=True)
    @mock.patch.object(ilo_common, 'update_secure_boot_mode', spec_set=True,
                       autospec=True)
    def test_prepare_instance_boot_from_volume(
            self, update_secure_boot_mode_mock,
            update_boot_mode_mock, set_boot_device_mock,
            set_iscsi_boot_target_mock, get_boot_mode_mock,
            is_iscsi_boot_mock, cleanup_vmedia_boot_mock):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            driver_internal_info = task.node.driver_internal_info
            driver_internal_info['ilo_uefi_iscsi_boot'] = True
            task.node.driver_internal_info = driver_internal_info
            task.node.save()
            is_iscsi_boot_mock.return_value = True
            get_boot_mode_mock.return_value = 'uefi'
            task.driver.boot.prepare_instance(task)
            cleanup_vmedia_boot_mock.assert_called_once_with(task)
            set_iscsi_boot_target_mock.assert_called_once_with(mock.ANY, task)
            set_boot_device_mock.assert_called_once_with(
                task, boot_devices.ISCSIBOOT, persistent=True)
            update_boot_mode_mock.assert_called_once_with(task)
            update_secure_boot_mode_mock.assert_called_once_with(task, True)
            self.assertTrue(task.node.driver_internal_info.get(
                            'ilo_uefi_iscsi_boot'))

    @mock.patch.object(ilo_common, 'cleanup_vmedia_boot', spec_set=True,
                       autospec=True)
    @mock.patch.object(deploy_utils, 'is_iscsi_boot',
                       spec_set=True, autospec=True)
    @mock.patch.object(boot_mode_utils, 'get_boot_mode_for_deploy',
                       spec_set=True, autospec=True)
    def test_prepare_instance_boot_from_volume_bios(
            self, get_boot_mode_mock,
            is_iscsi_boot_mock, cleanup_vmedia_boot_mock):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            is_iscsi_boot_mock.return_value = True
            get_boot_mode_mock.return_value = 'bios'
            self.assertRaisesRegex(exception.InstanceDeployFailure,
                                   "Virtual media can not boot volume "
                                   "in BIOS boot mode.",
                                   task.driver.boot.prepare_instance, task)
            cleanup_vmedia_boot_mock.assert_called_once_with(task)
            self.assertIsNone(task.node.driver_internal_info.get(
                              'ilo_uefi_iscsi_boot'))

    @mock.patch.object(ilo_common, 'cleanup_vmedia_boot', spec_set=True,
                       autospec=True)
    @mock.patch.object(deploy_utils, 'is_iscsi_boot',
                       spec_set=True, autospec=True)
    @mock.patch.object(ilo_common, 'setup_vmedia_for_boot',
                       spec_set=True, autospec=True)
    @mock.patch.object(ilo_boot, '_get_boot_iso',
                       spec_set=True, autospec=True)
    @mock.patch.object(manager_utils, 'node_set_boot_device', spec_set=True,
                       autospec=True)
    @mock.patch.object(ilo_common, 'update_boot_mode', spec_set=True,
                       autospec=True)
    @mock.patch.object(ilo_common, 'update_secure_boot_mode', spec_set=True,
                       autospec=True)
    def test_prepare_instance_boot_ramdisk(self, update_secure_boot_mode_mock,
                                           update_boot_mode_mock,
                                           set_boot_device_mock,
                                           get_boot_iso_mock,
                                           setup_vmedia_mock,
                                           is_iscsi_boot_mock,
                                           cleanup_vmedia_boot_mock):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            instance_info = task.node.instance_info
            instance_info['capabilities'] = '{"boot_option": "ramdisk"}'
            task.node.instance_info = instance_info
            task.node.save()
            is_iscsi_boot_mock.return_value = False
            url = 'http://myserver/boot.iso'
            get_boot_iso_mock.return_value = url
            task.driver.boot.prepare_instance(task)
            cleanup_vmedia_boot_mock.assert_called_once_with(task)
            get_boot_iso_mock.assert_called_once_with(task, None)
            setup_vmedia_mock.assert_called_once_with(task, url)
            set_boot_device_mock.assert_called_once_with(
                task, boot_devices.CDROM, persistent=True)
            update_boot_mode_mock.assert_called_once_with(task)
            update_secure_boot_mode_mock.assert_called_once_with(task, True)

    def test_validate_rescue(self):
        driver_info = self.node.driver_info
        driver_info['ilo_rescue_iso'] = 'rescue.iso'
        self.node.driver_info = driver_info
        self.node.save()
        with task_manager.acquire(self.context, self.node.uuid) as task:
            task.driver.boot.validate_rescue(task)

    def test_validate_rescue_no_rescue_ramdisk(self):
        with task_manager.acquire(self.context, self.node.uuid) as task:
            self.assertRaisesRegex(exception.MissingParameterValue,
                                   'Missing.*ilo_rescue_iso',
                                   task.driver.boot.validate_rescue, task)


class IloPXEBootTestCase(test_common.BaseIloTest):

    boot_interface = 'ilo-pxe'

    @mock.patch.object(ilo_boot, 'prepare_node_for_deploy', spec_set=True,
                       autospec=True)
    @mock.patch.object(pxe.PXEBoot, 'prepare_ramdisk', spec_set=True,
                       autospec=True)
    def _test_prepare_ramdisk_needs_node_prep(self, pxe_prepare_ramdisk_mock,
                                              prepare_node_mock, prov_state):
        self.node.provision_state = prov_state
        self.node.save()
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            self.assertIsNone(
                task.driver.boot.prepare_ramdisk(task, None))

            prepare_node_mock.assert_called_once_with(task)
            pxe_prepare_ramdisk_mock.assert_called_once_with(
                mock.ANY, task, None)

    def test_prepare_ramdisk_in_deploying(self):
        self._test_prepare_ramdisk_needs_node_prep(prov_state=states.DEPLOYING)

    def test_prepare_ramdisk_in_rescuing(self):
        self._test_prepare_ramdisk_needs_node_prep(prov_state=states.RESCUING)

    def test_prepare_ramdisk_in_cleaning(self):
        self._test_prepare_ramdisk_needs_node_prep(prov_state=states.CLEANING)

    @mock.patch.object(deploy_utils, 'is_iscsi_boot',
                       spec_set=True, autospec=True)
    @mock.patch.object(ilo_common, 'update_secure_boot_mode', spec_set=True,
                       autospec=True)
    @mock.patch.object(manager_utils, 'node_power_action', spec_set=True,
                       autospec=True)
    @mock.patch.object(pxe.PXEBoot, 'clean_up_instance', spec_set=True,
                       autospec=True)
    def test_clean_up_instance(self, pxe_cleanup_mock, node_power_mock,
                               update_secure_boot_mode_mock,
                               is_iscsi_boot_mock):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.driver.boot.clean_up_instance(task)
            is_iscsi_boot_mock.return_value = False
            node_power_mock.assert_called_once_with(task, states.POWER_OFF)
            update_secure_boot_mode_mock.assert_called_once_with(task, False)
            pxe_cleanup_mock.assert_called_once_with(mock.ANY, task)

    @mock.patch.object(deploy_utils, 'is_iscsi_boot',
                       spec_set=True, autospec=True)
    @mock.patch.object(ilo_common, 'update_secure_boot_mode', spec_set=True,
                       autospec=True)
    @mock.patch.object(manager_utils, 'node_power_action', spec_set=True,
                       autospec=True)
    @mock.patch.object(pxe.PXEBoot, 'clean_up_instance', spec_set=True,
                       autospec=True)
    def test_clean_up_instance_boot_from_volume_bios(
            self, pxe_cleanup_mock, node_power_mock,
            update_secure_boot_mode_mock, is_iscsi_boot_mock):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.driver.boot.clean_up_instance(task)
            is_iscsi_boot_mock.return_value = True
            node_power_mock.assert_called_once_with(task, states.POWER_OFF)
            update_secure_boot_mode_mock.assert_called_once_with(task, False)
            pxe_cleanup_mock.assert_called_once_with(mock.ANY, task)

    @mock.patch.object(deploy_utils, 'is_iscsi_boot',
                       spec_set=True, autospec=True)
    @mock.patch.object(ilo_management.IloManagement, 'clear_iscsi_boot_target',
                       spec_set=True, autospec=True)
    @mock.patch.object(ilo_common, 'update_secure_boot_mode', spec_set=True,
                       autospec=True)
    @mock.patch.object(manager_utils, 'node_power_action', spec_set=True,
                       autospec=True)
    def test_clean_up_instance_boot_from_volume(self, node_power_mock,
                                                update_secure_boot_mode_mock,
                                                clear_iscsi_boot_target_mock,
                                                is_iscsi_boot_mock):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            driver_internal_info = task.node.driver_internal_info
            driver_internal_info['ilo_uefi_iscsi_boot'] = True
            task.node.driver_internal_info = driver_internal_info
            task.node.save()
            is_iscsi_boot_mock.return_value = True
            task.driver.boot.clean_up_instance(task)
            clear_iscsi_boot_target_mock.assert_called_once_with(mock.ANY,
                                                                 task)
            node_power_mock.assert_called_once_with(task, states.POWER_OFF)
            update_secure_boot_mode_mock.assert_called_once_with(task, False)
            self.assertIsNone(task.node.driver_internal_info.get(
                              'ilo_uefi_iscsi_boot'))

    @mock.patch.object(deploy_utils, 'is_iscsi_boot',
                       spec_set=True, autospec=True)
    @mock.patch.object(boot_mode_utils, 'get_boot_mode_for_deploy',
                       spec_set=True, autospec=True)
    @mock.patch.object(ilo_common, 'update_secure_boot_mode', spec_set=True,
                       autospec=True)
    @mock.patch.object(ilo_common, 'update_boot_mode', spec_set=True,
                       autospec=True)
    @mock.patch.object(pxe.PXEBoot, 'prepare_instance', spec_set=True,
                       autospec=True)
    def test_prepare_instance(self, pxe_prepare_instance_mock,
                              update_boot_mode_mock,
                              update_secure_boot_mode_mock,
                              get_boot_mode_mock,
                              is_iscsi_boot_mock):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.driver.boot.prepare_instance(task)
            is_iscsi_boot_mock.return_value = False
            get_boot_mode_mock.return_value = 'uefi'
            update_boot_mode_mock.assert_called_once_with(task)
            update_secure_boot_mode_mock.assert_called_once_with(task, True)
            pxe_prepare_instance_mock.assert_called_once_with(mock.ANY, task)
            self.assertIsNone(task.node.driver_internal_info.get(
                              'ilo_uefi_iscsi_boot'))

    @mock.patch.object(deploy_utils, 'is_iscsi_boot',
                       spec_set=True, autospec=True)
    @mock.patch.object(boot_mode_utils, 'get_boot_mode_for_deploy',
                       spec_set=True, autospec=True)
    @mock.patch.object(ilo_common, 'update_secure_boot_mode', spec_set=True,
                       autospec=True)
    @mock.patch.object(ilo_common, 'update_boot_mode', spec_set=True,
                       autospec=True)
    @mock.patch.object(pxe.PXEBoot, 'prepare_instance', spec_set=True,
                       autospec=True)
    def test_prepare_instance_bios(self, pxe_prepare_instance_mock,
                                   update_boot_mode_mock,
                                   update_secure_boot_mode_mock,
                                   get_boot_mode_mock,
                                   is_iscsi_boot_mock):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.driver.boot.prepare_instance(task)
            is_iscsi_boot_mock.return_value = False
            get_boot_mode_mock.return_value = 'bios'
            update_boot_mode_mock.assert_called_once_with(task)
            update_secure_boot_mode_mock.assert_called_once_with(task, True)
            pxe_prepare_instance_mock.assert_called_once_with(mock.ANY, task)
            self.assertIsNone(task.node.driver_internal_info.get(
                              'ilo_uefi_iscsi_boot'))

    @mock.patch.object(deploy_utils, 'is_iscsi_boot',
                       spec_set=True, autospec=True)
    @mock.patch.object(boot_mode_utils, 'get_boot_mode_for_deploy',
                       spec_set=True, autospec=True)
    @mock.patch.object(ilo_management.IloManagement, 'set_iscsi_boot_target',
                       spec_set=True, autospec=True)
    @mock.patch.object(manager_utils, 'node_set_boot_device', spec_set=True,
                       autospec=True)
    @mock.patch.object(ilo_common, 'update_boot_mode', spec_set=True,
                       autospec=True)
    @mock.patch.object(ilo_common, 'update_secure_boot_mode', spec_set=True,
                       autospec=True)
    def test_prepare_instance_boot_from_volume(
            self, update_secure_boot_mode_mock,
            update_boot_mode_mock, set_boot_device_mock,
            set_iscsi_boot_target_mock, get_boot_mode_mock,
            is_iscsi_boot_mock):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            is_iscsi_boot_mock.return_value = True
            get_boot_mode_mock.return_value = 'uefi'
            task.driver.boot.prepare_instance(task)
            set_iscsi_boot_target_mock.assert_called_once_with(mock.ANY, task)
            set_boot_device_mock.assert_called_once_with(
                task, boot_devices.ISCSIBOOT, persistent=True)
            update_boot_mode_mock.assert_called_once_with(task)
            update_secure_boot_mode_mock.assert_called_once_with(task, True)
            self.assertTrue(task.node.driver_internal_info.get(
                            'ilo_uefi_iscsi_boot'))


@mock.patch.object(ipxe.iPXEBoot, '__init__', lambda self: None)
class IloiPXEBootTestCase(test_common.BaseIloTest):

    boot_interface = 'ilo-ipxe'

    def setUp(self):
        super(IloiPXEBootTestCase, self).setUp()
        self.config(enabled_boot_interfaces=['ilo-ipxe'])

    @mock.patch.object(ilo_boot, 'prepare_node_for_deploy', spec_set=True,
                       autospec=True)
    @mock.patch.object(ipxe.iPXEBoot, 'prepare_ramdisk', spec_set=True,
                       autospec=True)
    def _test_prepare_ramdisk_needs_node_prep(self, pxe_prepare_ramdisk_mock,
                                              prepare_node_mock, prov_state):
        self.node.provision_state = prov_state
        self.node.save()
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            self.assertIsNone(
                task.driver.boot.prepare_ramdisk(task, None))

            prepare_node_mock.assert_called_once_with(task)
            pxe_prepare_ramdisk_mock.assert_called_once_with(
                mock.ANY, task, None)

    def test_prepare_ramdisk_in_deploying(self):
        self._test_prepare_ramdisk_needs_node_prep(prov_state=states.DEPLOYING)

    def test_prepare_ramdisk_in_rescuing(self):
        self._test_prepare_ramdisk_needs_node_prep(prov_state=states.RESCUING)

    def test_prepare_ramdisk_in_cleaning(self):
        self._test_prepare_ramdisk_needs_node_prep(prov_state=states.CLEANING)

    @mock.patch.object(deploy_utils, 'is_iscsi_boot',
                       spec_set=True, autospec=True)
    @mock.patch.object(ilo_common, 'update_secure_boot_mode', spec_set=True,
                       autospec=True)
    @mock.patch.object(manager_utils, 'node_power_action', spec_set=True,
                       autospec=True)
    @mock.patch.object(ipxe.iPXEBoot, 'clean_up_instance', spec_set=True,
                       autospec=True)
    def test_clean_up_instance(self, pxe_cleanup_mock, node_power_mock,
                               update_secure_boot_mode_mock,
                               is_iscsi_boot_mock):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.driver.boot.clean_up_instance(task)
            is_iscsi_boot_mock.return_value = False
            node_power_mock.assert_called_once_with(task, states.POWER_OFF)
            update_secure_boot_mode_mock.assert_called_once_with(task, False)
            pxe_cleanup_mock.assert_called_once_with(mock.ANY, task)

    @mock.patch.object(deploy_utils, 'is_iscsi_boot',
                       spec_set=True, autospec=True)
    @mock.patch.object(ilo_common, 'update_secure_boot_mode', spec_set=True,
                       autospec=True)
    @mock.patch.object(manager_utils, 'node_power_action', spec_set=True,
                       autospec=True)
    @mock.patch.object(ipxe.iPXEBoot, 'clean_up_instance', spec_set=True,
                       autospec=True)
    def test_clean_up_instance_boot_from_volume_bios(
            self, pxe_cleanup_mock, node_power_mock,
            update_secure_boot_mode_mock, is_iscsi_boot_mock):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.driver.boot.clean_up_instance(task)
            is_iscsi_boot_mock.return_value = True
            node_power_mock.assert_called_once_with(task, states.POWER_OFF)
            update_secure_boot_mode_mock.assert_called_once_with(task, False)
            pxe_cleanup_mock.assert_called_once_with(mock.ANY, task)

    @mock.patch.object(deploy_utils, 'is_iscsi_boot',
                       spec_set=True, autospec=True)
    @mock.patch.object(ilo_management.IloManagement, 'clear_iscsi_boot_target',
                       spec_set=True, autospec=True)
    @mock.patch.object(ilo_common, 'update_secure_boot_mode', spec_set=True,
                       autospec=True)
    @mock.patch.object(manager_utils, 'node_power_action', spec_set=True,
                       autospec=True)
    def test_clean_up_instance_boot_from_volume(self, node_power_mock,
                                                update_secure_boot_mode_mock,
                                                clear_iscsi_boot_target_mock,
                                                is_iscsi_boot_mock):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            driver_internal_info = task.node.driver_internal_info
            driver_internal_info['ilo_uefi_iscsi_boot'] = True
            task.node.driver_internal_info = driver_internal_info
            task.node.save()
            is_iscsi_boot_mock.return_value = True
            task.driver.boot.clean_up_instance(task)
            clear_iscsi_boot_target_mock.assert_called_once_with(mock.ANY,
                                                                 task)
            node_power_mock.assert_called_once_with(task, states.POWER_OFF)
            update_secure_boot_mode_mock.assert_called_once_with(task, False)
            self.assertIsNone(task.node.driver_internal_info.get(
                              'ilo_uefi_iscsi_boot'))

    @mock.patch.object(deploy_utils, 'is_iscsi_boot',
                       spec_set=True, autospec=True)
    @mock.patch.object(boot_mode_utils, 'get_boot_mode_for_deploy',
                       spec_set=True, autospec=True)
    @mock.patch.object(ilo_common, 'update_secure_boot_mode', spec_set=True,
                       autospec=True)
    @mock.patch.object(ilo_common, 'update_boot_mode', spec_set=True,
                       autospec=True)
    @mock.patch.object(ipxe.iPXEBoot, 'prepare_instance', spec_set=True,
                       autospec=True)
    def test_prepare_instance(self, pxe_prepare_instance_mock,
                              update_boot_mode_mock,
                              update_secure_boot_mode_mock,
                              get_boot_mode_mock,
                              is_iscsi_boot_mock):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.driver.boot.prepare_instance(task)
            is_iscsi_boot_mock.return_value = False
            get_boot_mode_mock.return_value = 'uefi'
            update_boot_mode_mock.assert_called_once_with(task)
            update_secure_boot_mode_mock.assert_called_once_with(task, True)
            pxe_prepare_instance_mock.assert_called_once_with(mock.ANY, task)
            self.assertIsNone(task.node.driver_internal_info.get(
                              'ilo_uefi_iscsi_boot'))

    @mock.patch.object(deploy_utils, 'is_iscsi_boot',
                       spec_set=True, autospec=True)
    @mock.patch.object(boot_mode_utils, 'get_boot_mode_for_deploy',
                       spec_set=True, autospec=True)
    @mock.patch.object(ilo_common, 'update_secure_boot_mode', spec_set=True,
                       autospec=True)
    @mock.patch.object(ilo_common, 'update_boot_mode', spec_set=True,
                       autospec=True)
    @mock.patch.object(ipxe.iPXEBoot, 'prepare_instance', spec_set=True,
                       autospec=True)
    def test_prepare_instance_bios(self, pxe_prepare_instance_mock,
                                   update_boot_mode_mock,
                                   update_secure_boot_mode_mock,
                                   get_boot_mode_mock,
                                   is_iscsi_boot_mock):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.driver.boot.prepare_instance(task)
            is_iscsi_boot_mock.return_value = False
            get_boot_mode_mock.return_value = 'bios'
            update_boot_mode_mock.assert_called_once_with(task)
            update_secure_boot_mode_mock.assert_called_once_with(task, True)
            pxe_prepare_instance_mock.assert_called_once_with(mock.ANY, task)
            self.assertIsNone(task.node.driver_internal_info.get(
                              'ilo_uefi_iscsi_boot'))

    @mock.patch.object(deploy_utils, 'is_iscsi_boot',
                       spec_set=True, autospec=True)
    @mock.patch.object(boot_mode_utils, 'get_boot_mode_for_deploy',
                       spec_set=True, autospec=True)
    @mock.patch.object(ilo_management.IloManagement, 'set_iscsi_boot_target',
                       spec_set=True, autospec=True)
    @mock.patch.object(manager_utils, 'node_set_boot_device', spec_set=True,
                       autospec=True)
    @mock.patch.object(ilo_common, 'update_boot_mode', spec_set=True,
                       autospec=True)
    @mock.patch.object(ilo_common, 'update_secure_boot_mode', spec_set=True,
                       autospec=True)
    def test_prepare_instance_boot_from_volume(
            self, update_secure_boot_mode_mock,
            update_boot_mode_mock, set_boot_device_mock,
            set_iscsi_boot_target_mock, get_boot_mode_mock,
            is_iscsi_boot_mock):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            is_iscsi_boot_mock.return_value = True
            get_boot_mode_mock.return_value = 'uefi'
            task.driver.boot.prepare_instance(task)
            set_iscsi_boot_target_mock.assert_called_once_with(mock.ANY, task)
            set_boot_device_mock.assert_called_once_with(
                task, boot_devices.ISCSIBOOT, persistent=True)
            update_boot_mode_mock.assert_called_once_with(task)
            update_secure_boot_mode_mock.assert_called_once_with(task, True)
            self.assertTrue(task.node.driver_internal_info.get(
                            'ilo_uefi_iscsi_boot'))
