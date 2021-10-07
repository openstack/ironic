# Copyright 2019 Red Hat, Inc.
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

import collections
import os
import tempfile
from unittest import mock

from oslo_utils import importutils
from oslo_utils import uuidutils

from ironic.common import images
from ironic.common import states
from ironic.common import utils
from ironic.conductor import task_manager
from ironic.drivers.modules import deploy_utils
from ironic.drivers.modules import image_utils
from ironic.tests.unit.db import base as db_base
from ironic.tests.unit.db import utils as db_utils
from ironic.tests.unit.objects import utils as obj_utils

sushy = importutils.try_import('sushy')

INFO_DICT = db_utils.get_test_redfish_info()
INFO_DICT_ILO = db_utils.get_test_ilo_info()


class RedfishImageHandlerTestCase(db_base.DbTestCase):

    def setUp(self):
        super(RedfishImageHandlerTestCase, self).setUp()
        self.config(enabled_hardware_types=['redfish'],
                    enabled_power_interfaces=['redfish'],
                    enabled_boot_interfaces=['redfish-virtual-media'],
                    enabled_management_interfaces=['redfish'],
                    enabled_inspect_interfaces=['redfish'],
                    enabled_bios_interfaces=['redfish'])
        self.node = obj_utils.create_test_node(
            self.context, driver='redfish', driver_info=INFO_DICT)

    def test__append_filename_param_without_qs(self):
        img_handler_obj = image_utils.ImageHandler(self.node.driver)
        res = img_handler_obj._append_filename_param(
            'http://a.b/c', 'b.img')
        expected = 'http://a.b/c?filename=b.img'
        self.assertEqual(expected, res)

    def test__append_filename_param_with_qs(self):
        img_handler_obj = image_utils.ImageHandler(self.node.driver)
        res = img_handler_obj._append_filename_param(
            'http://a.b/c?d=e&f=g', 'b.img')
        expected = 'http://a.b/c?d=e&f=g&filename=b.img'
        self.assertEqual(expected, res)

    def test__append_filename_param_with_filename(self):
        img_handler_obj = image_utils.ImageHandler(self.node.driver)
        res = img_handler_obj._append_filename_param(
            'http://a.b/c?filename=bootme.img', 'b.img')
        expected = 'http://a.b/c?filename=bootme.img'
        self.assertEqual(expected, res)

    @mock.patch.object(image_utils, 'swift', autospec=True)
    def test_publish_image_swift(self, mock_swift):
        img_handler_obj = image_utils.ImageHandler(self.node.driver)
        mock_swift_api = mock_swift.SwiftAPI.return_value
        mock_swift_api.get_temp_url.return_value = 'https://a.b/c.f?e=f'

        url = img_handler_obj.publish_image('file.iso', 'boot.iso')

        self.assertEqual(
            'https://a.b/c.f?e=f&filename=file.iso', url)

        mock_swift.SwiftAPI.assert_called_once_with()

        mock_swift_api.create_object.assert_called_once_with(
            mock.ANY, mock.ANY, mock.ANY, mock.ANY)

        mock_swift_api.get_temp_url.assert_called_once_with(
            mock.ANY, mock.ANY, mock.ANY)

    @mock.patch.object(image_utils, 'swift', autospec=True)
    def test_unpublish_image_swift(self, mock_swift):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            img_handler_obj = image_utils.ImageHandler(self.node.driver)
            object_name = 'image-%s' % task.node.uuid

            img_handler_obj.unpublish_image(object_name)

            mock_swift.SwiftAPI.assert_called_once_with()
            mock_swift_api = mock_swift.SwiftAPI.return_value

            mock_swift_api.delete_object.assert_called_once_with(
                'ironic_redfish_container', object_name)

    @mock.patch.object(os, 'chmod', autospec=True)
    @mock.patch.object(image_utils, 'shutil', autospec=True)
    @mock.patch.object(os, 'link', autospec=True)
    @mock.patch.object(os, 'mkdir', autospec=True)
    def test_publish_image_local_link(
            self, mock_mkdir, mock_link, mock_shutil, mock_chmod):
        self.config(use_swift=False, group='redfish')
        self.config(http_url='http://localhost', group='deploy')
        img_handler_obj = image_utils.ImageHandler(self.node.driver)

        url = img_handler_obj.publish_image('file.iso', 'boot.iso')

        self.assertEqual(
            'http://localhost/redfish/boot.iso', url)

        mock_mkdir.assert_called_once_with('/httpboot/redfish', 0o755)
        mock_link.assert_called_once_with(
            'file.iso', '/httpboot/redfish/boot.iso')
        mock_chmod.assert_called_once_with('file.iso', 0o644)

    @mock.patch.object(os, 'chmod', autospec=True)
    @mock.patch.object(image_utils, 'shutil', autospec=True)
    @mock.patch.object(os, 'link', autospec=True)
    @mock.patch.object(os, 'mkdir', autospec=True)
    def test_publish_image_external_ip(
            self, mock_mkdir, mock_link, mock_shutil, mock_chmod):
        self.config(use_swift=False, group='redfish')
        self.config(http_url='http://localhost',
                    external_http_url='http://non-local.host',
                    group='deploy')
        img_handler_obj = image_utils.ImageHandler(self.node.driver)

        url = img_handler_obj.publish_image('file.iso', 'boot.iso')

        self.assertEqual(
            'http://non-local.host/redfish/boot.iso', url)

        mock_mkdir.assert_called_once_with('/httpboot/redfish', 0o755)
        mock_link.assert_called_once_with(
            'file.iso', '/httpboot/redfish/boot.iso')
        mock_chmod.assert_called_once_with('file.iso', 0o644)

    @mock.patch.object(os, 'chmod', autospec=True)
    @mock.patch.object(image_utils, 'shutil', autospec=True)
    @mock.patch.object(os, 'link', autospec=True)
    @mock.patch.object(os, 'mkdir', autospec=True)
    def test_publish_image_local_copy(self, mock_mkdir, mock_link,
                                      mock_shutil, mock_chmod):
        self.config(use_swift=False, group='redfish')
        self.config(http_url='http://localhost', group='deploy')
        img_handler_obj = image_utils.ImageHandler(self.node.driver)

        mock_link.side_effect = OSError()

        url = img_handler_obj.publish_image('file.iso', 'boot.iso')

        self.assertEqual(
            'http://localhost/redfish/boot.iso', url)

        mock_mkdir.assert_called_once_with('/httpboot/redfish', 0o755)

        mock_shutil.copyfile.assert_called_once_with(
            'file.iso', '/httpboot/redfish/boot.iso')
        mock_chmod.assert_called_once_with('/httpboot/redfish/boot.iso',
                                           0o644)

    @mock.patch.object(image_utils, 'ironic_utils', autospec=True)
    def test_unpublish_image_local(self, mock_ironic_utils):
        self.config(use_swift=False, group='redfish')
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            img_handler_obj = image_utils.ImageHandler(self.node.driver)
            object_name = 'image-%s' % task.node.uuid

            expected_file = '/httpboot/redfish/' + object_name

            img_handler_obj.unpublish_image(object_name)

            mock_ironic_utils.unlink_without_raise.assert_called_once_with(
                expected_file)


class IloImageHandlerTestCase(db_base.DbTestCase):

    def setUp(self):
        super(IloImageHandlerTestCase, self).setUp()
        self.config(enabled_hardware_types=['ilo'],
                    enabled_power_interfaces=['ilo'],
                    enabled_boot_interfaces=['ilo-virtual-media'],
                    enabled_management_interfaces=['ilo'],
                    enabled_inspect_interfaces=['ilo'],
                    enabled_bios_interfaces=['ilo'])
        self.node = obj_utils.create_test_node(
            self.context, driver='ilo', driver_info=INFO_DICT_ILO)

    def test_ilo_kernel_param_config(self):
        self.config(kernel_append_params="console=ttyS1", group='ilo')
        img_handler_obj = image_utils.ImageHandler(self.node.driver)
        actual_k_param = img_handler_obj.kernel_params
        expected_k_param = "console=ttyS1"

        self.assertEqual(expected_k_param, actual_k_param)


class Ilo5ImageHandlerTestCase(db_base.DbTestCase):

    def setUp(self):
        super(Ilo5ImageHandlerTestCase, self).setUp()
        self.config(enabled_hardware_types=['ilo5'],
                    enabled_power_interfaces=['ilo'],
                    enabled_boot_interfaces=['ilo-virtual-media'],
                    enabled_management_interfaces=['ilo5'],
                    enabled_inspect_interfaces=['ilo'],
                    enabled_bios_interfaces=['ilo'])
        self.node = obj_utils.create_test_node(
            self.context, driver='ilo5', driver_info=INFO_DICT_ILO)

    def test_ilo5_kernel_param_config(self):
        self.config(kernel_append_params="console=ttyS1", group='ilo')
        img_handler_obj = image_utils.ImageHandler(self.node.driver)
        actual_k_param = img_handler_obj.kernel_params
        expected_k_param = "console=ttyS1"

        self.assertEqual(expected_k_param, actual_k_param)


class RedfishImageUtilsTestCase(db_base.DbTestCase):

    def setUp(self):
        super(RedfishImageUtilsTestCase, self).setUp()
        self.config(enabled_hardware_types=['redfish'],
                    enabled_power_interfaces=['redfish'],
                    enabled_boot_interfaces=['redfish-virtual-media'],
                    enabled_management_interfaces=['redfish'],
                    enabled_inspect_interfaces=['redfish'],
                    enabled_bios_interfaces=['redfish'])
        self.node = obj_utils.create_test_node(
            self.context, driver='redfish', driver_info=INFO_DICT,
            provision_state=states.DEPLOYING)

    @mock.patch.object(image_utils.ImageHandler, 'unpublish_image',
                       autospec=True)
    def test_cleanup_floppy_image(self, mock_unpublish):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            image_utils.cleanup_floppy_image(task)

            object_name = 'image-%s' % task.node.uuid

            mock_unpublish.assert_called_once_with(mock.ANY, object_name)

    @mock.patch.object(image_utils.ImageHandler, 'publish_image',
                       autospec=True)
    @mock.patch.object(images, 'create_vfat_image', autospec=True)
    def test_prepare_floppy_image(
            self, mock_create_vfat_image, mock_publish_image):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            expected_url = 'https://a.b/c.f?e=f'

            mock_publish_image.return_value = expected_url

            url = image_utils.prepare_floppy_image(task)

            object_name = 'image-%s' % task.node.uuid

            mock_publish_image.assert_called_once_with(mock.ANY,
                                                       mock.ANY, object_name)

            mock_create_vfat_image.assert_called_once_with(
                mock.ANY, parameters=None)

            self.assertEqual(expected_url, url)

    @mock.patch.object(image_utils.ImageHandler, 'publish_image',
                       autospec=True)
    @mock.patch.object(images, 'create_vfat_image', autospec=True)
    def test_prepare_floppy_image_with_external_ip(
            self, mock_create_vfat_image, mock_publish_image):
        self.config(external_callback_url='http://callback/', group='deploy')
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            expected_url = 'https://a.b/c.f?e=f'

            mock_publish_image.return_value = expected_url

            url = image_utils.prepare_floppy_image(task)

            object_name = 'image-%s' % task.node.uuid

            mock_publish_image.assert_called_once_with(mock.ANY,
                                                       mock.ANY, object_name)

            mock_create_vfat_image.assert_called_once_with(
                mock.ANY, parameters={"ipa-api-url": "http://callback"})

            self.assertEqual(expected_url, url)

    @mock.patch.object(image_utils.ImageHandler, 'publish_image',
                       autospec=True)
    def test_prepare_disk_image(self, mock_publish_image):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            expected_url = 'https://a.b/c.f?e=f'
            expected_object_name = task.node.uuid

            def _publish(img_handler, tmp_file, object_name):
                self.assertEqual(expected_object_name, object_name)
                self.assertEqual(b'content', open(tmp_file, 'rb').read())
                return expected_url

            mock_publish_image.side_effect = _publish

            url = image_utils.prepare_disk_image(task, b'content')

            mock_publish_image.assert_called_once_with(mock.ANY, mock.ANY,
                                                       expected_object_name)

            self.assertEqual(expected_url, url)

    @mock.patch.object(image_utils.ImageHandler, 'publish_image',
                       autospec=True)
    def test_prepare_disk_image_prefix(self, mock_publish_image):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            expected_url = 'https://a.b/c.f?e=f'
            expected_object_name = 'configdrive-%s' % task.node.uuid

            def _publish(img_handler, tmp_file, object_name):
                self.assertEqual(expected_object_name, object_name)
                self.assertEqual(b'content', open(tmp_file, 'rb').read())
                return expected_url

            mock_publish_image.side_effect = _publish

            url = image_utils.prepare_disk_image(task, b'content',
                                                 prefix='configdrive')

            mock_publish_image.assert_called_once_with(mock.ANY, mock.ANY,
                                                       expected_object_name)

            self.assertEqual(expected_url, url)

    @mock.patch.object(image_utils.ImageHandler, 'publish_image',
                       autospec=True)
    def test_prepare_disk_image_file(self, mock_publish_image):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            expected_url = 'https://a.b/c.f?e=f'
            expected_object_name = task.node.uuid

            def _publish(img_handler, tmp_file, object_name):
                self.assertEqual(expected_object_name, object_name)
                self.assertEqual(b'content', open(tmp_file, 'rb').read())
                return expected_url

            mock_publish_image.side_effect = _publish

            with tempfile.NamedTemporaryFile() as fp:
                fp.write(b'content')
                fp.flush()
                url = image_utils.prepare_disk_image(task, fp.name)

            mock_publish_image.assert_called_once_with(mock.ANY, mock.ANY,
                                                       expected_object_name)

            self.assertEqual(expected_url, url)

    @mock.patch.object(image_utils, 'prepare_disk_image', autospec=True)
    def test_prepare_configdrive_image(self, mock_prepare):
        expected_url = 'https://a.b/c.f?e=f'
        encoded = 'H4sIAPJ8418C/0vOzytJzSsBAKkwxf4HAAAA'

        def _prepare(task, content, prefix):
            with open(content, 'rb') as fp:
                self.assertEqual(b'content', fp.read())
            return expected_url

        mock_prepare.side_effect = _prepare

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            result = image_utils.prepare_configdrive_image(task, encoded)
            self.assertEqual(expected_url, result)

    @mock.patch.object(utils, 'execute', autospec=True)
    @mock.patch.object(images, 'fetch_into', autospec=True)
    @mock.patch.object(image_utils, 'prepare_disk_image', autospec=True)
    def test_prepare_configdrive_image_url(self, mock_prepare, mock_fetch,
                                           mock_execute):
        content = 'https://swift/path'
        expected_url = 'https://a.b/c.f?e=f'
        encoded = b'H4sIAPJ8418C/0vOzytJzSsBAKkwxf4HAAAA'

        def _fetch(context, image_href, image_file):
            self.assertEqual(content, image_href)
            image_file.write(encoded)

        def _prepare(task, content, prefix):
            with open(content, 'rb') as fp:
                self.assertEqual(b'content', fp.read())
            return expected_url

        mock_fetch.side_effect = _fetch
        mock_prepare.side_effect = _prepare
        mock_execute.return_value = 'text/plain', ''

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            result = image_utils.prepare_configdrive_image(task, content)
            self.assertEqual(expected_url, result)

    @mock.patch.object(utils, 'execute', autospec=True)
    @mock.patch.object(images, 'fetch_into', autospec=True)
    @mock.patch.object(image_utils, 'prepare_disk_image', autospec=True)
    def test_prepare_configdrive_image_binary_url(self, mock_prepare,
                                                  mock_fetch, mock_execute):
        content = 'https://swift/path'
        expected_url = 'https://a.b/c.f?e=f'

        def _fetch(context, image_href, image_file):
            self.assertEqual(content, image_href)
            image_file.write(b'content')

        def _prepare(task, content, prefix):
            with open(content, 'rb') as fp:
                self.assertEqual(b'content', fp.read())
            return expected_url

        mock_fetch.side_effect = _fetch
        mock_prepare.side_effect = _prepare
        mock_execute.return_value = 'application/octet-stream'

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            result = image_utils.prepare_configdrive_image(task, content)
            self.assertEqual(expected_url, result)

    @mock.patch.object(image_utils.ImageHandler, 'unpublish_image',
                       autospec=True)
    def test_cleanup_iso_image(self, mock_unpublish):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            image_utils.cleanup_iso_image(task)

            object_name = 'boot-%s.iso' % task.node.uuid

            mock_unpublish.assert_called_once_with(mock.ANY, object_name)

    @mock.patch.object(image_utils.ImageHandler, 'publish_image',
                       autospec=True)
    @mock.patch.object(images, 'create_boot_iso', autospec=True)
    def test__prepare_iso_image_uefi(
            self, mock_create_boot_iso, mock_publish_image):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            task.node.instance_info.update(deploy_boot_mode='uefi')

            expected_url = 'https://a.b/c.f?e=f'

            mock_publish_image.return_value = expected_url

            url = image_utils._prepare_iso_image(
                task, 'http://kernel/img', 'http://ramdisk/img',
                'http://bootloader/img', root_uuid=task.node.uuid)

            object_name = 'boot-%s.iso' % task.node.uuid

            mock_publish_image.assert_called_once_with(
                mock.ANY, mock.ANY, object_name)

            mock_create_boot_iso.assert_called_once_with(
                mock.ANY, mock.ANY, 'http://kernel/img', 'http://ramdisk/img',
                boot_mode='uefi', esp_image_href='http://bootloader/img',
                kernel_params='nofb nomodeset vga=normal',
                root_uuid='1be26c0b-03f2-4d2e-ae87-c02d7f33c123',
                inject_files=None)

            self.assertEqual(expected_url, url)

    @mock.patch.object(image_utils.ImageHandler, 'publish_image',
                       autospec=True)
    @mock.patch.object(images, 'create_boot_iso', autospec=True)
    def test__prepare_iso_image_default_boot_mode(
            self, mock_create_boot_iso, mock_publish_image):
        self.config(default_boot_mode='uefi', group='deploy')
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            image_utils._prepare_iso_image(
                task, 'http://kernel/img', 'http://ramdisk/img',
                bootloader_href=None, root_uuid=task.node.uuid)

            mock_create_boot_iso.assert_called_once_with(
                mock.ANY, mock.ANY, 'http://kernel/img', 'http://ramdisk/img',
                boot_mode='uefi', esp_image_href=None,
                kernel_params='nofb nomodeset vga=normal',
                root_uuid='1be26c0b-03f2-4d2e-ae87-c02d7f33c123',
                inject_files=None)

    @mock.patch.object(image_utils.ImageHandler, 'publish_image',
                       autospec=True)
    @mock.patch.object(images, 'create_boot_iso', autospec=True)
    def test__prepare_iso_image_bios(
            self, mock_create_boot_iso, mock_publish_image):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:

            expected_url = 'https://a.b/c.f?e=f'

            mock_publish_image.return_value = expected_url

            url = image_utils._prepare_iso_image(
                task, 'http://kernel/img', 'http://ramdisk/img',
                bootloader_href=None, root_uuid=task.node.uuid, base_iso=None)

            object_name = 'boot-%s.iso' % task.node.uuid

            mock_publish_image.assert_called_once_with(
                mock.ANY, mock.ANY, object_name)

            mock_create_boot_iso.assert_called_once_with(
                mock.ANY, mock.ANY, 'http://kernel/img', 'http://ramdisk/img',
                boot_mode='bios', esp_image_href=None,
                kernel_params='nofb nomodeset vga=normal',
                root_uuid='1be26c0b-03f2-4d2e-ae87-c02d7f33c123',
                inject_files=None)

            self.assertEqual(expected_url, url)

    @mock.patch.object(image_utils.ImageHandler, 'publish_image',
                       autospec=True)
    @mock.patch.object(images, 'create_boot_iso', autospec=True)
    def test__prepare_iso_image_kernel_params(
            self, mock_create_boot_iso, mock_publish_image):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            kernel_params = 'network-config=base64-cloudinit-blob'

            task.node.instance_info.update(kernel_append_params=kernel_params)

            image_utils._prepare_iso_image(
                task, 'http://kernel/img', 'http://ramdisk/img',
                bootloader_href=None, root_uuid=task.node.uuid)

            mock_create_boot_iso.assert_called_once_with(
                mock.ANY, mock.ANY, 'http://kernel/img', 'http://ramdisk/img',
                boot_mode='bios', esp_image_href=None,
                kernel_params=kernel_params,
                root_uuid='1be26c0b-03f2-4d2e-ae87-c02d7f33c123',
                inject_files=None)

    @mock.patch.object(image_utils.ImageHandler, 'publish_image',
                       autospec=True)
    @mock.patch.object(images, 'create_boot_iso', autospec=True)
    def test__prepare_iso_image_kernel_params_driver_info(
            self, mock_create_boot_iso, mock_publish_image):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            kernel_params = 'network-config=base64-cloudinit-blob'

            task.node.driver_info['kernel_append_params'] = kernel_params

            image_utils._prepare_iso_image(
                task, 'http://kernel/img', 'http://ramdisk/img',
                bootloader_href=None, root_uuid=task.node.uuid)

            mock_create_boot_iso.assert_called_once_with(
                mock.ANY, mock.ANY, 'http://kernel/img', 'http://ramdisk/img',
                boot_mode='bios', esp_image_href=None,
                kernel_params=kernel_params,
                root_uuid='1be26c0b-03f2-4d2e-ae87-c02d7f33c123',
                inject_files=None)

    @mock.patch.object(deploy_utils, 'get_boot_option', lambda node: 'ramdisk')
    @mock.patch.object(image_utils.ImageHandler, 'publish_image',
                       autospec=True)
    @mock.patch.object(images, 'create_boot_iso', autospec=True)
    def test__prepare_iso_image_kernel_params_for_ramdisk(
            self, mock_create_boot_iso, mock_publish_image):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            kernel_params = 'network-config=base64-cloudinit-blob'

            task.node.instance_info['ramdisk_kernel_arguments'] = kernel_params

            image_utils._prepare_iso_image(
                task, 'http://kernel/img', 'http://ramdisk/img',
                bootloader_href=None, root_uuid=task.node.uuid)

            mock_create_boot_iso.assert_called_once_with(
                mock.ANY, mock.ANY, 'http://kernel/img', 'http://ramdisk/img',
                boot_mode='bios', esp_image_href=None,
                kernel_params="root=/dev/ram0 text " + kernel_params,
                root_uuid='1be26c0b-03f2-4d2e-ae87-c02d7f33c123',
                inject_files=None)

    @mock.patch.object(deploy_utils, 'get_boot_option', lambda node: 'ramdisk')
    @mock.patch.object(image_utils.ImageHandler, 'publish_image',
                       autospec=True)
    @mock.patch.object(images, 'create_boot_iso', autospec=True)
    def test__prepare_iso_image_kernel_params_for_ramdisk_cleaning(
            self, mock_create_boot_iso, mock_publish_image):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            kernel_params = 'network-config=base64-cloudinit-blob'

            task.node.driver_info['kernel_append_params'] = kernel_params
            task.node.provision_state = states.CLEANING

            image_utils._prepare_iso_image(
                task, 'http://kernel/img', 'http://ramdisk/img',
                bootloader_href=None, root_uuid=task.node.uuid)

            mock_create_boot_iso.assert_called_once_with(
                mock.ANY, mock.ANY, 'http://kernel/img', 'http://ramdisk/img',
                boot_mode='bios', esp_image_href=None,
                kernel_params=kernel_params,
                root_uuid='1be26c0b-03f2-4d2e-ae87-c02d7f33c123',
                inject_files=None)

    @mock.patch.object(image_utils.ImageHandler, 'publish_image',
                       autospec=True)
    @mock.patch.object(images, 'create_boot_iso', autospec=True)
    def test__prepare_iso_image_extra_params(
            self, mock_create_boot_iso, mock_publish_image):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            kernel_params = 'network-config=base64-cloudinit-blob'
            extra_params = collections.OrderedDict([('foo', 'bar'),
                                                    ('banana', None)])
            self.config(kernel_append_params=kernel_params, group='redfish')

            image_utils._prepare_iso_image(
                task, 'http://kernel/img', 'http://ramdisk/img',
                root_uuid=task.node.uuid, params=extra_params)

            mock_create_boot_iso.assert_called_once_with(
                mock.ANY, mock.ANY, 'http://kernel/img', 'http://ramdisk/img',
                boot_mode='bios', esp_image_href=None,
                kernel_params=kernel_params + ' foo=bar banana',
                root_uuid='1be26c0b-03f2-4d2e-ae87-c02d7f33c123',
                inject_files=None)

    def test__prepare_iso_image_bootable_iso(self):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            base_image_url = 'http://bearmetal.net/boot.iso'
            self.config(ramdisk_image_download_source='http', group='deploy')
            url = image_utils._prepare_iso_image(
                task, None, None, bootloader_href=None, root_uuid=None,
                base_iso=base_image_url)
            self.assertEqual(url, base_image_url)

    @mock.patch.object(deploy_utils, 'get_boot_option', lambda node: 'ramdisk')
    def test__prepare_iso_image_bootable_iso_with_instance_info(self):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            base_image_url = 'http://bearmetal.net/boot.iso'
            task.node.instance_info['ramdisk_image_download_source'] = 'http'
            url = image_utils._prepare_iso_image(
                task, None, None, bootloader_href=None, root_uuid=None,
                base_iso=base_image_url)
            self.assertEqual(url, base_image_url)

    @mock.patch.object(image_utils.ImageHandler, 'publish_image',
                       autospec=True)
    @mock.patch.object(image_utils, 'ISOImageCache', autospec=True)
    @mock.patch.object(images, 'create_boot_iso', autospec=True)
    def test__prepare_iso_image_bootable_iso_file(self, mock_create_boot_iso,
                                                  mock_cache,
                                                  mock_publish_image):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            base_image_url = '/path/to/baseiso'
            self.config(ramdisk_image_download_source='http', group='deploy')
            image_utils._prepare_iso_image(
                task, 'http://kernel/img', 'http://ramdisk/img',
                bootloader_href=None, root_uuid=task.node.uuid,
                base_iso=base_image_url)
            mock_cache.return_value.fetch_image.assert_called_once_with(
                base_image_url, mock.ANY, ctx=task.context, force_raw=False)
            mock_create_boot_iso.assert_not_called()

    @mock.patch.object(images, 'get_temp_url_for_glance_image',
                       autospec=True)
    def test__prepare_iso_image_bootable_iso_from_swift(self, mock_temp_url):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            base_image_url = uuidutils.generate_uuid()
            self.config(ramdisk_image_download_source='swift', group='deploy')
            url = image_utils._prepare_iso_image(
                task, None, None, bootloader_href=None, root_uuid=None,
                base_iso=base_image_url)
            self.assertEqual(mock_temp_url.return_value, url)
            mock_temp_url.assert_called_once_with(task.context, base_image_url)

    def test__prepare_iso_image_bootable_iso_swift_noop(self):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            base_image_url = 'http://bearmetal.net/boot.iso'
            self.config(ramdisk_image_download_source='swift', group='deploy')
            url = image_utils._prepare_iso_image(
                task, None, None, bootloader_href=None, root_uuid=None,
                base_iso=base_image_url)
            self.assertEqual(url, base_image_url)

    def test__prepare_iso_image_bootable_iso_swift_schema(self):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            base_image_url = 'swift://bearmetal.net/boot.iso'
            url = image_utils._prepare_iso_image(
                task, None, None, bootloader_href=None, root_uuid=None,
                base_iso=base_image_url)
            self.assertEqual(url, base_image_url)

    def test__find_param(self):
        param_dict = {
            'deploy_kernel': 'kernel',
            'deploy_ramdisk': 'ramdisk',
            'bootloader': 'bootloader'
        }
        param_str = "deploy_kernel"
        expected = "kernel"

        actual = image_utils._find_param(param_str, param_dict)
        self.assertEqual(actual, expected)

    def test__find_param_not_found(self):
        param_dict = {
            'deploy_ramdisk': 'ramdisk',
            'bootloader': 'bootloader'
        }
        param_str = "deploy_kernel"
        expected = None
        actual = image_utils._find_param(param_str, param_dict)
        self.assertEqual(actual, expected)

    @mock.patch.object(image_utils, '_prepare_iso_image', autospec=True)
    def test_prepare_deploy_iso(self, mock__prepare_iso_image):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:

            d_info = {
                'deploy_kernel': 'kernel',
                'deploy_ramdisk': 'ramdisk',
                'bootloader': 'bootloader'
            }
            task.node.driver_info.update(d_info)

            task.node.instance_info.update(deploy_boot_mode='uefi')

            image_utils.prepare_deploy_iso(task, {}, 'deploy', d_info)

            mock__prepare_iso_image.assert_called_once_with(
                task, 'kernel', 'ramdisk', 'bootloader', params={},
                inject_files={}, base_iso=None)

    @mock.patch.object(image_utils, '_prepare_iso_image', autospec=True)
    def test_prepare_deploy_iso_existing_iso(self, mock__prepare_iso_image):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:

            d_info = {
                'deploy_iso': 'iso',
            }
            task.node.driver_info.update(d_info)

            task.node.instance_info.update(deploy_boot_mode='uefi')

            image_utils.prepare_deploy_iso(task, {}, 'deploy', d_info)

            mock__prepare_iso_image.assert_called_once_with(
                task, None, None, None, params={},
                inject_files={}, base_iso='iso')

    @mock.patch.object(image_utils, '_prepare_iso_image', autospec=True)
    def test_prepare_deploy_iso_existing_iso_vendor_prefix(
            self, mock__prepare_iso_image):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:

            d_info = {
                'redfish_deploy_iso': 'iso',
            }
            task.node.driver_info.update(d_info)

            task.node.instance_info.update(deploy_boot_mode='uefi')

            image_utils.prepare_deploy_iso(task, {}, 'deploy', d_info)

            mock__prepare_iso_image.assert_called_once_with(
                task, None, None, None, params={},
                inject_files={}, base_iso='iso')

    @mock.patch.object(image_utils, '_prepare_iso_image', autospec=True)
    def test_prepare_deploy_iso_network_data(self, mock__prepare_iso_image):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:

            d_info = {
                'deploy_kernel': 'kernel',
                'deploy_ramdisk': 'ramdisk'
            }
            task.node.driver_info.update(d_info)

            task.node.instance_info.update()

            network_data = {'a': ['b']}

            mock_get_node_nw_data = mock.MagicMock(return_value=network_data)
            task.driver.network.get_node_network_data = mock_get_node_nw_data

            image_utils.prepare_deploy_iso(task, {}, 'deploy', d_info)

            expected_files = {
                b"""{
  "a": [
    "b"
  ]
}""": 'openstack/latest/network_data.json'
            }

            mock__prepare_iso_image.assert_called_once_with(
                task, 'kernel', 'ramdisk', bootloader_href=None,
                params={}, inject_files=expected_files, base_iso=None)

    @mock.patch.object(image_utils, '_prepare_iso_image', autospec=True)
    def test_prepare_deploy_iso_tls(self, mock__prepare_iso_image):
        with tempfile.NamedTemporaryFile(delete=False) as tf:
            temp_name = tf.name
            self.addCleanup(lambda: os.unlink(temp_name))
            self.config(api_ca_file=temp_name, group='agent')
            tf.write(b'I can haz SSLz')

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:

            d_info = {
                'deploy_kernel': 'kernel',
                'deploy_ramdisk': 'ramdisk',
                'bootloader': 'bootloader'
            }
            task.node.driver_info.update(d_info)

            task.node.instance_info.update(deploy_boot_mode='uefi')

            image_utils.prepare_deploy_iso(task, {}, 'deploy', d_info)

            expected_files = {
                b"""[DEFAULT]
cafile = /etc/ironic-python-agent/ironic.crt
""": 'etc/ironic-python-agent.d/ironic-tls.conf',
                temp_name: 'etc/ironic-python-agent/ironic.crt'
            }

            mock__prepare_iso_image.assert_called_once_with(
                task, 'kernel', 'ramdisk', 'bootloader', params={},
                inject_files=expected_files, base_iso=None)

    @mock.patch.object(image_utils, '_prepare_iso_image', autospec=True)
    def test_prepare_deploy_iso_external_ip(self, mock__prepare_iso_image):
        self.config(external_callback_url='http://callback/', group='deploy')
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:

            d_info = {
                'deploy_kernel': 'kernel',
                'deploy_ramdisk': 'ramdisk',
                'bootloader': 'bootloader'
            }
            task.node.driver_info.update(d_info)

            task.node.instance_info.update(deploy_boot_mode='uefi')

            image_utils.prepare_deploy_iso(task, {}, 'deploy', d_info)

            mock__prepare_iso_image.assert_called_once_with(
                task, 'kernel', 'ramdisk', 'bootloader',
                params={'ipa-api-url': 'http://callback'},
                inject_files={}, base_iso=None)

    @mock.patch.object(image_utils, '_find_param', autospec=True)
    @mock.patch.object(image_utils, '_prepare_iso_image', autospec=True)
    @mock.patch.object(images, 'create_boot_iso', autospec=True)
    def test_prepare_boot_iso(self, mock_create_boot_iso,
                              mock__prepare_iso_image, find_mock):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            d_info = {
                'deploy_kernel': 'kernel',
                'deploy_ramdisk': 'ramdisk',
                'bootloader': 'bootloader'
            }
            task.node.driver_info.update(d_info)

            task.node.instance_info.update(
                {'image_source': 'http://boot/iso',
                 'kernel': 'http://kernel/img',
                 'ramdisk': 'http://ramdisk/img'})

            find_call_list = [
                mock.call('bootloader', d_info)
            ]

            find_mock.side_effect = [
                'bootloader'
            ]

            image_utils.prepare_boot_iso(
                task, d_info, root_uuid=task.node.uuid)

            mock__prepare_iso_image.assert_called_once_with(
                mock.ANY, 'http://kernel/img', 'http://ramdisk/img',
                'bootloader', root_uuid=task.node.uuid,
                base_iso=None)

            find_mock.assert_has_calls(find_call_list)

    @mock.patch.object(image_utils, '_find_param', autospec=True)
    @mock.patch.object(image_utils, '_prepare_iso_image', autospec=True)
    @mock.patch.object(images, 'create_boot_iso', autospec=True)
    def test_prepare_boot_iso_user_supplied(self, mock_create_boot_iso,
                                            mock__prepare_iso_image,
                                            find_mock):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            d_info = {
                'deploy_kernel': 'kernel',
                'deploy_ramdisk': 'ramdisk',
                'bootloader': 'bootloader'
            }
            task.node.driver_info.update(d_info)

            task.node.instance_info.update(
                {'boot_iso': 'http://boot/iso'})

            find_call_list = [
                mock.call('bootloader', d_info)
            ]

            find_mock.side_effect = [
                'bootloader'
            ]
            image_utils.prepare_boot_iso(
                task, d_info, root_uuid=task.node.uuid)

            mock__prepare_iso_image.assert_called_once_with(
                mock.ANY, None, None,
                'bootloader', root_uuid=task.node.uuid,
                base_iso='http://boot/iso')

            find_mock.assert_has_calls(find_call_list)
