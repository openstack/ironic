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

import tempfile

import mock
from oslo_config import cfg
import six

from ironic.common import images
from ironic.common import swift
from ironic.conductor import task_manager
from ironic.drivers.modules import deploy_utils
from ironic.drivers.modules import virtual_media_base
from ironic.drivers import utils as driver_utils
from ironic.tests.unit.db import base as db_base
from ironic.tests.unit.db import utils as db_utils
from ironic.tests.unit.objects import utils as object_utils

if six.PY3:
    import io
    file = io.BytesIO

INFO_DICT = db_utils.get_test_redfish_info()

CONF = cfg.CONF


class VirtualMediaCommonMethodsTestCase(db_base.DbTestCase):

    def setUp(self):
        super(VirtualMediaCommonMethodsTestCase, self).setUp()
        self.config(enabled_hardware_types=['ilo', 'fake-hardware'],
                    enabled_boot_interfaces=['ilo-pxe', 'ilo-virtual-media',
                                             'fake'],
                    enabled_bios_interfaces=['ilo', 'no-bios'],
                    enabled_power_interfaces=['ilo', 'fake'],
                    enabled_management_interfaces=['ilo', 'fake'],
                    enabled_inspect_interfaces=['ilo', 'fake', 'no-inspect'],
                    enabled_console_interfaces=['ilo', 'fake', 'no-console'],
                    enabled_vendor_interfaces=['ilo', 'fake', 'no-vendor'])
        self.node = object_utils.create_test_node(
            self.context, boot_interface='ilo-virtual-media',
            deploy_interface='direct')

    def test_get_iso_image_name(self):
        boot_iso_actual = virtual_media_base.get_iso_image_name(self.node)
        boot_iso_expected = "boot-%s" % self.node.uuid
        self.assertEqual(boot_iso_expected, boot_iso_actual)

    @mock.patch.object(tempfile, 'NamedTemporaryFile', spec_set=True,
                       autospec=True)
    @mock.patch.object(images, 'create_boot_iso', spec_set=True, autospec=True)
    @mock.patch.object(swift, 'SwiftAPI', spec_set=True, autospec=True)
    @mock.patch.object(virtual_media_base, 'get_iso_image_name',
                       spec_set=True, autospec=True)
    @mock.patch.object(driver_utils, 'get_node_capability', spec_set=True,
                       autospec=True)
    def test__prepare_iso_image_uefi(self, capability_mock,
                                     iso_image_name_mock, swift_api_mock,
                                     create_boot_iso_mock, tempfile_mock):
        CONF.ilo.swift_ilo_container = 'ilo-cont'
        CONF.ilo.use_web_server_for_images = False

        swift_obj_mock = swift_api_mock.return_value
        fileobj_mock = mock.MagicMock(spec=file)
        fileobj_mock.name = 'tmpfile'
        mock_file_handle = mock.MagicMock(spec=file)
        mock_file_handle.__enter__.return_value = fileobj_mock
        tempfile_mock.return_value = mock_file_handle
        iso_image_name_mock.return_value = 'abcdef'
        create_boot_iso_mock.return_value = '/path/to/boot-iso'
        capability_mock.return_value = 'uefi'

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            boot_iso_actual = virtual_media_base.prepare_iso_image(
                task, 'kernel_uuid', 'ramdisk_uuid',
                deploy_iso_href='deploy_iso_uuid',
                bootloader_href='bootloader_uuid',
                root_uuid='root-uuid',
                kernel_params='kernel-params',
                timeout=None,
                container=CONF.ilo.swift_ilo_container,
                use_web_server=CONF.ilo.use_web_server_for_images)
            iso_image_name_mock.assert_called_once_with(task.node)
            create_boot_iso_mock.assert_called_once_with(
                task.context, 'tmpfile', 'kernel_uuid', 'ramdisk_uuid',
                deploy_iso_href='deploy_iso_uuid',
                esp_image_href='bootloader_uuid',
                root_uuid='root-uuid',
                kernel_params='kernel-params',
                boot_mode='uefi')
            swift_obj_mock.create_object.assert_called_once_with(
                'ilo-cont', 'abcdef', 'tmpfile', None)
            boot_iso_expected = 'swift:abcdef'
            self.assertEqual(boot_iso_expected, boot_iso_actual)

    @mock.patch.object(tempfile, 'NamedTemporaryFile', spec_set=True,
                       autospec=True)
    @mock.patch.object(images, 'create_boot_iso', spec_set=True, autospec=True)
    @mock.patch.object(swift, 'SwiftAPI', spec_set=True, autospec=True)
    @mock.patch.object(virtual_media_base, 'get_iso_image_name',
                       spec_set=True, autospec=True)
    @mock.patch.object(driver_utils, 'get_node_capability', spec_set=True,
                       autospec=True)
    def test__prepare_iso_image_bios(self, capability_mock,
                                     iso_image_name_mock, swift_api_mock,
                                     create_boot_iso_mock, tempfile_mock):
        CONF.ilo.swift_ilo_container = 'ilo-cont'
        CONF.ilo.use_web_server_for_images = False

        swift_obj_mock = swift_api_mock.return_value
        fileobj_mock = mock.MagicMock(spec=file)
        fileobj_mock.name = 'tmpfile'
        mock_file_handle = mock.MagicMock(spec=file)
        mock_file_handle.__enter__.return_value = fileobj_mock
        tempfile_mock.return_value = mock_file_handle
        iso_image_name_mock.return_value = 'abcdef'
        create_boot_iso_mock.return_value = '/path/to/boot-iso'
        capability_mock.return_value = 'bios'

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            boot_iso_actual = virtual_media_base.prepare_iso_image(
                task, 'kernel_uuid', 'ramdisk_uuid',
                deploy_iso_href='deploy_iso_uuid',
                root_uuid='root-uuid',
                kernel_params='kernel-params',
                timeout=None,
                container=CONF.ilo.swift_ilo_container,
                use_web_server=CONF.ilo.use_web_server_for_images)
            iso_image_name_mock.assert_called_once_with(task.node)
            create_boot_iso_mock.assert_called_once_with(
                task.context, 'tmpfile', 'kernel_uuid', 'ramdisk_uuid',
                deploy_iso_href='deploy_iso_uuid',
                esp_image_href=None,
                root_uuid='root-uuid',
                kernel_params='kernel-params',
                boot_mode='bios')
            swift_obj_mock.create_object.assert_called_once_with(
                'ilo-cont', 'abcdef', 'tmpfile', None)
            boot_iso_expected = 'swift:abcdef'
            self.assertEqual(boot_iso_expected, boot_iso_actual)

    @mock.patch.object(deploy_utils, 'copy_image_to_web_server', spec_set=True,
                       autospec=True)
    @mock.patch.object(tempfile, 'NamedTemporaryFile', spec_set=True,
                       autospec=True)
    @mock.patch.object(images, 'create_boot_iso', spec_set=True, autospec=True)
    @mock.patch.object(virtual_media_base, 'get_iso_image_name',
                       spec_set=True, autospec=True)
    @mock.patch.object(driver_utils, 'get_node_capability', spec_set=True,
                       autospec=True)
    def test__prepare_iso_image_use_webserver(self, capability_mock,
                                              iso_image_name_mock,
                                              create_boot_iso_mock,
                                              tempfile_mock, copy_file_mock):
        CONF.ilo.use_web_server_for_images = True
        CONF.deploy.http_url = "http://10.10.1.30/httpboot"
        CONF.deploy.http_root = "/httpboot"
        CONF.pxe.pxe_append_params = 'kernel-params'

        fileobj_mock = mock.MagicMock(spec=file)
        fileobj_mock.name = 'tmpfile'
        mock_file_handle = mock.MagicMock(spec=file)
        mock_file_handle.__enter__.return_value = fileobj_mock
        tempfile_mock.return_value = mock_file_handle

        ramdisk_href = "http://10.10.1.30/httpboot/ramdisk"
        kernel_href = "http://10.10.1.30/httpboot/kernel"
        iso_image_name_mock.return_value = 'new_boot_iso'
        create_boot_iso_mock.return_value = '/path/to/boot-iso'
        capability_mock.return_value = 'uefi'
        copy_file_mock.return_value = "http://10.10.1.30/httpboot/new_boot_iso"

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            driver_internal_info = task.node.driver_internal_info
            driver_internal_info['boot_iso_created_in_web_server'] = True
            boot_iso_actual = virtual_media_base.prepare_iso_image(
                task, kernel_href, ramdisk_href,
                deploy_iso_href='deploy_iso_uuid',
                bootloader_href='bootloader_uuid',
                root_uuid='root-uuid',
                kernel_params='kernel-params',
                use_web_server=CONF.ilo.use_web_server_for_images)
            iso_image_name_mock.assert_called_once_with(task.node)
            create_boot_iso_mock.assert_called_once_with(
                task.context, 'tmpfile', kernel_href, ramdisk_href,
                deploy_iso_href='deploy_iso_uuid',
                esp_image_href='bootloader_uuid',
                root_uuid='root-uuid',
                kernel_params='kernel-params',
                boot_mode='uefi')
            boot_iso_expected = 'http://10.10.1.30/httpboot/new_boot_iso'
            self.assertEqual(boot_iso_expected, boot_iso_actual)
            copy_file_mock.assert_called_once_with(fileobj_mock.name,
                                                   'new_boot_iso')

    @mock.patch.object(virtual_media_base, 'prepare_iso_image', spec_set=True,
                       autospec=True)
    def test_prepare_deploy_iso(self, prepare_iso_mock):
        driver_info = {'deploy_kernel': 'kernel', 'deploy_ramdisk': 'ramdisk',
                       'bootloader': 'bootloader'}
        CONF.pxe.pxe_append_params = 'kernel-params'
        timeout = None
        container = 'container'
        prepare_iso_mock.return_value = (
            'swift:boot-b5451849-e088-4a4c-aa5f-4d97b3371dec')

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            deploy_iso_actual = virtual_media_base.prepare_deploy_iso(
                task, {}, 'deploy', driver_info, use_web_server=False,
                container=container)
            prepare_iso_mock.assert_called_once_with(
                task, 'kernel', 'ramdisk', bootloader_href='bootloader',
                kernel_params=CONF.pxe.pxe_append_params, timeout=timeout,
                use_web_server=False, container='container')
            deploy_iso_expected = (
                'swift:boot-b5451849-e088-4a4c-aa5f-4d97b3371dec')
            self.assertEqual(deploy_iso_expected, deploy_iso_actual)
