# coding=utf-8

# Copyright 2013 Hewlett-Packard Development Company, L.P.
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

import builtins
import io
import os
import shutil
from unittest import mock

from ironic_lib import disk_utils
from oslo_concurrency import processutils
from oslo_config import cfg

from ironic.common import exception
from ironic.common.glance_service import service_utils as glance_utils
from ironic.common import image_service
from ironic.common import images
from ironic.common import utils
from ironic.tests import base

CONF = cfg.CONF


class IronicImagesTestCase(base.TestCase):

    class FakeImgInfo(object):
        pass

    @mock.patch.object(image_service, 'get_image_service', autospec=True)
    @mock.patch.object(builtins, 'open', autospec=True)
    def test_fetch_image_service(self, open_mock, image_service_mock):
        mock_file_handle = mock.MagicMock(spec=io.BytesIO)
        mock_file_handle.__enter__.return_value = 'file'
        open_mock.return_value = mock_file_handle

        images.fetch('context', 'image_href', 'path')

        open_mock.assert_called_once_with('path', 'wb')
        image_service_mock.assert_called_once_with('image_href',
                                                   context='context')
        image_service_mock.return_value.download.assert_called_once_with(
            'image_href', 'file')

    @mock.patch.object(image_service, 'get_image_service', autospec=True)
    @mock.patch.object(images, 'image_to_raw', autospec=True)
    @mock.patch.object(builtins, 'open', autospec=True)
    def test_fetch_image_service_force_raw(self, open_mock, image_to_raw_mock,
                                           image_service_mock):
        mock_file_handle = mock.MagicMock(spec=io.BytesIO)
        mock_file_handle.__enter__.return_value = 'file'
        open_mock.return_value = mock_file_handle

        images.fetch('context', 'image_href', 'path', force_raw=True)

        open_mock.assert_called_once_with('path', 'wb')
        image_service_mock.return_value.download.assert_called_once_with(
            'image_href', 'file')
        image_to_raw_mock.assert_called_once_with(
            'image_href', 'path', 'path.part')

    @mock.patch.object(disk_utils, 'qemu_img_info', autospec=True)
    def test_image_to_raw_no_file_format(self, qemu_img_info_mock):
        info = self.FakeImgInfo()
        info.file_format = None
        qemu_img_info_mock.return_value = info

        e = self.assertRaises(exception.ImageUnacceptable, images.image_to_raw,
                              'image_href', 'path', 'path_tmp')
        qemu_img_info_mock.assert_called_once_with('path_tmp')
        self.assertIn("'qemu-img info' parsing failed.", str(e))

    @mock.patch.object(disk_utils, 'qemu_img_info', autospec=True)
    def test_image_to_raw_backing_file_present(self, qemu_img_info_mock):
        info = self.FakeImgInfo()
        info.file_format = 'raw'
        info.backing_file = 'backing_file'
        qemu_img_info_mock.return_value = info

        e = self.assertRaises(exception.ImageUnacceptable, images.image_to_raw,
                              'image_href', 'path', 'path_tmp')
        qemu_img_info_mock.assert_called_once_with('path_tmp')
        self.assertIn("fmt=raw backed by: backing_file", str(e))

    @mock.patch.object(os, 'rename', autospec=True)
    @mock.patch.object(os, 'unlink', autospec=True)
    @mock.patch.object(disk_utils, 'convert_image', autospec=True)
    @mock.patch.object(disk_utils, 'qemu_img_info', autospec=True)
    def test_image_to_raw(self, qemu_img_info_mock, convert_image_mock,
                          unlink_mock, rename_mock):
        CONF.set_override('force_raw_images', True)
        info = self.FakeImgInfo()
        info.file_format = 'fmt'
        info.backing_file = None
        qemu_img_info_mock.return_value = info

        def convert_side_effect(source, dest, out_format):
            info.file_format = 'raw'
        convert_image_mock.side_effect = convert_side_effect

        images.image_to_raw('image_href', 'path', 'path_tmp')

        qemu_img_info_mock.assert_has_calls([mock.call('path_tmp'),
                                             mock.call('path.converted')])
        convert_image_mock.assert_called_once_with('path_tmp',
                                                   'path.converted', 'raw')
        unlink_mock.assert_called_once_with('path_tmp')
        rename_mock.assert_called_once_with('path.converted', 'path')

    @mock.patch.object(os, 'unlink', autospec=True)
    @mock.patch.object(disk_utils, 'convert_image', autospec=True)
    @mock.patch.object(disk_utils, 'qemu_img_info', autospec=True)
    def test_image_to_raw_not_raw_after_conversion(self, qemu_img_info_mock,
                                                   convert_image_mock,
                                                   unlink_mock):
        CONF.set_override('force_raw_images', True)
        info = self.FakeImgInfo()
        info.file_format = 'fmt'
        info.backing_file = None
        qemu_img_info_mock.return_value = info

        self.assertRaises(exception.ImageConvertFailed, images.image_to_raw,
                          'image_href', 'path', 'path_tmp')
        qemu_img_info_mock.assert_has_calls([mock.call('path_tmp'),
                                             mock.call('path.converted')])
        convert_image_mock.assert_called_once_with('path_tmp',
                                                   'path.converted', 'raw')
        unlink_mock.assert_called_once_with('path_tmp')

    @mock.patch.object(os, 'rename', autospec=True)
    @mock.patch.object(disk_utils, 'qemu_img_info', autospec=True)
    def test_image_to_raw_already_raw_format(self, qemu_img_info_mock,
                                             rename_mock):
        info = self.FakeImgInfo()
        info.file_format = 'raw'
        info.backing_file = None
        qemu_img_info_mock.return_value = info

        images.image_to_raw('image_href', 'path', 'path_tmp')

        qemu_img_info_mock.assert_called_once_with('path_tmp')
        rename_mock.assert_called_once_with('path_tmp', 'path')

    @mock.patch.object(image_service, 'get_image_service', autospec=True)
    def test_image_show_no_image_service(self, image_service_mock):
        images.image_show('context', 'image_href')
        image_service_mock.assert_called_once_with('image_href',
                                                   context='context')
        image_service_mock.return_value.show.assert_called_once_with(
            'image_href')

    def test_image_show_image_service(self):
        image_service_mock = mock.MagicMock()
        images.image_show('context', 'image_href', image_service_mock)
        image_service_mock.show.assert_called_once_with('image_href')

    @mock.patch.object(images, 'image_show', autospec=True)
    def test_download_size(self, show_mock):
        show_mock.return_value = {'size': 123456}
        size = images.download_size('context', 'image_href', 'image_service')
        self.assertEqual(123456, size)
        show_mock.assert_called_once_with('context', 'image_href',
                                          'image_service')

    @mock.patch.object(disk_utils, 'qemu_img_info', autospec=True)
    def test_converted_size_estimate_default(self, qemu_img_info_mock):
        info = self.FakeImgInfo()
        info.disk_size = 2
        info.virtual_size = 10 ** 10
        qemu_img_info_mock.return_value = info
        size = images.converted_size('path', estimate=True)
        qemu_img_info_mock.assert_called_once_with('path')
        self.assertEqual(4, size)

    @mock.patch.object(disk_utils, 'qemu_img_info', autospec=True)
    def test_converted_size_estimate_custom(self, qemu_img_info_mock):
        CONF.set_override('raw_image_growth_factor', 3)
        info = self.FakeImgInfo()
        info.disk_size = 2
        info.virtual_size = 10 ** 10
        qemu_img_info_mock.return_value = info
        size = images.converted_size('path', estimate=True)
        qemu_img_info_mock.assert_called_once_with('path')
        self.assertEqual(6, size)

    @mock.patch.object(disk_utils, 'qemu_img_info', autospec=True)
    def test_converted_size_estimate_raw_smaller(self, qemu_img_info_mock):
        CONF.set_override('raw_image_growth_factor', 3)
        info = self.FakeImgInfo()
        info.disk_size = 2
        info.virtual_size = 5
        qemu_img_info_mock.return_value = info
        size = images.converted_size('path', estimate=True)
        qemu_img_info_mock.assert_called_once_with('path')
        self.assertEqual(5, size)

    @mock.patch.object(images, 'get_image_properties', autospec=True)
    @mock.patch.object(glance_utils, 'is_glance_image', autospec=True)
    def test_is_whole_disk_image_no_img_src(self, mock_igi, mock_gip):
        instance_info = {'image_source': ''}
        iwdi = images.is_whole_disk_image('context', instance_info)
        self.assertIsNone(iwdi)
        self.assertFalse(mock_igi.called)
        self.assertFalse(mock_gip.called)

    @mock.patch.object(images, 'get_image_properties', autospec=True)
    @mock.patch.object(glance_utils, 'is_glance_image', autospec=True)
    def test_is_whole_disk_image_explicit(self, mock_igi, mock_gip):
        for value, result in [(images.IMAGE_TYPE_PARTITION, False),
                              (images.IMAGE_TYPE_WHOLE_DISK, True)]:
            instance_info = {'image_source': 'glance://partition_image',
                             'image_type': value}
            iwdi = images.is_whole_disk_image('context', instance_info)
            self.assertIs(iwdi, result)
            self.assertFalse(mock_igi.called)
            self.assertFalse(mock_gip.called)

    @mock.patch.object(images, 'get_image_properties', autospec=True)
    @mock.patch.object(glance_utils, 'is_glance_image', autospec=True)
    def test_is_whole_disk_image_partition_image(self, mock_igi, mock_gip):
        mock_igi.return_value = True
        mock_gip.return_value = {'kernel_id': 'kernel',
                                 'ramdisk_id': 'ramdisk'}
        instance_info = {'image_source': 'glance://partition_image'}
        image_source = instance_info['image_source']
        is_whole_disk_image = images.is_whole_disk_image('context',
                                                         instance_info)
        self.assertFalse(is_whole_disk_image)
        mock_igi.assert_called_once_with(image_source)
        mock_gip.assert_called_once_with('context', image_source)

    @mock.patch.object(images, 'get_image_properties', autospec=True)
    @mock.patch.object(glance_utils, 'is_glance_image', autospec=True)
    def test_is_whole_disk_image_whole_disk_image(self, mock_igi, mock_gip):
        mock_igi.return_value = True
        mock_gip.return_value = {}
        instance_info = {'image_source': 'glance://whole_disk_image'}
        image_source = instance_info['image_source']
        is_whole_disk_image = images.is_whole_disk_image('context',
                                                         instance_info)
        self.assertTrue(is_whole_disk_image)
        mock_igi.assert_called_once_with(image_source)
        mock_gip.assert_called_once_with('context', image_source)

    @mock.patch.object(images, 'get_image_properties', autospec=True)
    @mock.patch.object(glance_utils, 'is_glance_image', autospec=True)
    def test_is_whole_disk_image_partition_non_glance(self, mock_igi,
                                                      mock_gip):
        mock_igi.return_value = False
        instance_info = {'image_source': 'partition_image',
                         'kernel': 'kernel',
                         'ramdisk': 'ramdisk'}
        is_whole_disk_image = images.is_whole_disk_image('context',
                                                         instance_info)
        self.assertFalse(is_whole_disk_image)
        self.assertFalse(mock_gip.called)
        mock_igi.assert_called_once_with(instance_info['image_source'])

    @mock.patch.object(images, 'get_image_properties', autospec=True)
    @mock.patch.object(glance_utils, 'is_glance_image', autospec=True)
    def test_is_whole_disk_image_whole_disk_non_glance(self, mock_igi,
                                                       mock_gip):
        mock_igi.return_value = False
        instance_info = {'image_source': 'whole_disk_image'}
        is_whole_disk_image = images.is_whole_disk_image('context',
                                                         instance_info)
        self.assertTrue(is_whole_disk_image)
        self.assertFalse(mock_gip.called)
        mock_igi.assert_called_once_with(instance_info['image_source'])


class FsImageTestCase(base.TestCase):

    @mock.patch.object(builtins, 'open', autospec=True)
    @mock.patch.object(shutil, 'copyfile', autospec=True)
    @mock.patch.object(os, 'makedirs', autospec=True)
    def test__create_root_fs(self, mkdir_mock, cp_mock, open_mock):
        files_info = {
            'a1': 'b1',
            'a2': 'b2',
            'a3': 'sub_dir/b3',
            b'a4': 'b4'}

        images._create_root_fs('root_dir', files_info)

        cp_mock.assert_any_call('a1', 'root_dir/b1')
        cp_mock.assert_any_call('a2', 'root_dir/b2')
        cp_mock.assert_any_call('a3', 'root_dir/sub_dir/b3')

        open_mock.assert_called_once_with('root_dir/b4', 'wb')
        fp = open_mock.return_value.__enter__.return_value
        fp.write.assert_called_once_with(b'a4')

        mkdir_mock.assert_any_call('root_dir', exist_ok=True)
        mkdir_mock.assert_any_call('root_dir/sub_dir', exist_ok=True)

    @mock.patch.object(images, '_create_root_fs', autospec=True)
    @mock.patch.object(utils, 'tempdir', autospec=True)
    @mock.patch.object(utils, 'write_to_file', autospec=True)
    @mock.patch.object(utils, 'execute', autospec=True)
    def test_create_vfat_image(
            self, execute_mock, write_mock,
            tempdir_mock, create_root_fs_mock):

        mock_file_handle = mock.MagicMock(spec=io.BytesIO)
        mock_file_handle.__enter__.return_value = 'tempdir'
        tempdir_mock.return_value = mock_file_handle

        parameters = {'p1': 'v1'}
        files_info = {'a': 'b'}
        images.create_vfat_image('tgt_file', parameters=parameters,
                                 files_info=files_info, parameters_file='qwe',
                                 fs_size_kib=1000)

        execute_mock.assert_has_calls([
            mock.call('dd', 'if=/dev/zero', 'of=tgt_file', 'count=1',
                      'bs=1000KiB'),
            mock.call('mkfs', '-t', 'vfat', '-n', 'ir-vfd-de', 'tgt_file'),
            mock.call('mcopy', '-s', 'tempdir/*', '-i', 'tgt_file', '::')
        ])

        parameters_file_path = os.path.join('tempdir', 'qwe')
        write_mock.assert_called_once_with(parameters_file_path, 'p1=v1')
        create_root_fs_mock.assert_called_once_with('tempdir', files_info)

    @mock.patch.object(utils, 'execute', autospec=True)
    def test_create_vfat_image_dd_fails(self, execute_mock):

        execute_mock.side_effect = processutils.ProcessExecutionError
        self.assertRaises(exception.ImageCreationFailed,
                          images.create_vfat_image, 'tgt_file')

    @mock.patch.object(utils, 'tempdir', autospec=True)
    @mock.patch.object(utils, 'execute', autospec=True)
    def test_create_vfat_image_mkfs_fails(self, execute_mock,
                                          tempdir_mock):

        mock_file_handle = mock.MagicMock(spec=io.BytesIO)
        mock_file_handle.__enter__.return_value = 'tempdir'
        tempdir_mock.return_value = mock_file_handle

        execute_mock.side_effect = [None, processutils.ProcessExecutionError]
        self.assertRaises(exception.ImageCreationFailed,
                          images.create_vfat_image, 'tgt_file')

    @mock.patch.object(utils, 'umount', autospec=True)
    def test__umount_without_raise(self, umount_mock):

        umount_mock.side_effect = processutils.ProcessExecutionError
        images._umount_without_raise('mountdir')
        umount_mock.assert_called_once_with('mountdir')

    def test__generate_isolinux_cfg(self):

        kernel_params = ['key1=value1', 'key2']
        options = {'kernel': '/vmlinuz', 'ramdisk': '/initrd'}
        expected_cfg = ("default boot\n"
                        "\n"
                        "label boot\n"
                        "kernel /vmlinuz\n"
                        "append initrd=/initrd text key1=value1 key2 --")
        cfg = images._generate_cfg(kernel_params,
                                   CONF.isolinux_config_template,
                                   options)
        self.assertEqual(expected_cfg, cfg)

    def test__generate_grub_cfg(self):
        kernel_params = ['key1=value1', 'key2']
        options = {'linux': '/vmlinuz', 'initrd': '/initrd'}
        expected_cfg = ("set default=0\n"
                        "set timeout=5\n"
                        "set hidden_timeout_quiet=false\n"
                        "\n"
                        "menuentry \"boot_partition\" {\n"
                        "linuxefi /vmlinuz key1=value1 key2 --\n"
                        "initrdefi /initrd\n"
                        "}")

        cfg = images._generate_cfg(kernel_params,
                                   CONF.grub_config_template,
                                   options)
        self.assertEqual(expected_cfg, cfg)

    @mock.patch.object(os.path, 'relpath', autospec=True)
    @mock.patch.object(os, 'walk', autospec=True)
    @mock.patch.object(utils, 'mount', autospec=True)
    def test__mount_deploy_iso(self, mount_mock,
                               walk_mock, relpath_mock):
        walk_mock.return_value = [('/tmpdir1/EFI/ubuntu', [], ['grub.cfg']),
                                  ('/tmpdir1/isolinux', [],
                                   ['efiboot.img', 'isolinux.bin',
                                    'isolinux.cfg'])]
        relpath_mock.side_effect = ['EFI/ubuntu/grub.cfg',
                                    'isolinux/efiboot.img']

        images._mount_deploy_iso('path/to/deployiso', 'tmpdir1')
        mount_mock.assert_called_once_with('path/to/deployiso',
                                           'tmpdir1', '-o', 'loop')
        walk_mock.assert_called_once_with('tmpdir1')

    @mock.patch.object(images, '_umount_without_raise', autospec=True)
    @mock.patch.object(os.path, 'relpath', autospec=True)
    @mock.patch.object(os, 'walk', autospec=True)
    @mock.patch.object(utils, 'mount', autospec=True)
    def test__mount_deploy_iso_fail_no_esp_imageimg(self, mount_mock,
                                                    walk_mock, relpath_mock,
                                                    umount_mock):
        walk_mock.return_value = [('/tmpdir1/EFI/ubuntu', [], ['grub.cfg']),
                                  ('/tmpdir1/isolinux', [],
                                   ['isolinux.bin', 'isolinux.cfg'])]
        relpath_mock.side_effect = 'EFI/ubuntu/grub.cfg'

        self.assertRaises(exception.ImageCreationFailed,
                          images._mount_deploy_iso,
                          'path/to/deployiso', 'tmpdir1')
        mount_mock.assert_called_once_with('path/to/deployiso',
                                           'tmpdir1', '-o', 'loop')
        walk_mock.assert_called_once_with('tmpdir1')
        umount_mock.assert_called_once_with('tmpdir1')

    @mock.patch.object(images, '_umount_without_raise', autospec=True)
    @mock.patch.object(os.path, 'relpath', autospec=True)
    @mock.patch.object(os, 'walk', autospec=True)
    @mock.patch.object(utils, 'mount', autospec=True)
    def test__mount_deploy_iso_fails_no_grub_cfg(self, mount_mock,
                                                 walk_mock, relpath_mock,
                                                 umount_mock):
        walk_mock.return_value = [('/tmpdir1/EFI/ubuntu', '', []),
                                  ('/tmpdir1/isolinux', '',
                                   ['efiboot.img', 'isolinux.bin',
                                    'isolinux.cfg'])]
        relpath_mock.side_effect = 'isolinux/efiboot.img'

        self.assertRaises(exception.ImageCreationFailed,
                          images._mount_deploy_iso,
                          'path/to/deployiso', 'tmpdir1')
        mount_mock.assert_called_once_with('path/to/deployiso',
                                           'tmpdir1', '-o', 'loop')
        walk_mock.assert_called_once_with('tmpdir1')
        umount_mock.assert_called_once_with('tmpdir1')

    @mock.patch.object(utils, 'mount', autospec=True)
    def test__mount_deploy_iso_fail_with_ExecutionError(self, mount_mock):
        mount_mock.side_effect = processutils.ProcessExecutionError
        self.assertRaises(exception.ImageCreationFailed,
                          images._mount_deploy_iso,
                          'path/to/deployiso', 'tmpdir1')

    @mock.patch.object(images, '_umount_without_raise', autospec=True)
    @mock.patch.object(images, '_create_root_fs', autospec=True)
    @mock.patch.object(utils, 'write_to_file', autospec=True)
    @mock.patch.object(utils, 'execute', autospec=True)
    @mock.patch.object(images, '_mount_deploy_iso', autospec=True)
    @mock.patch.object(utils, 'tempdir', autospec=True)
    @mock.patch.object(images, '_generate_cfg', autospec=True)
    def test_create_esp_image_for_uefi_with_deploy_iso(
            self, gen_cfg_mock, tempdir_mock, mount_mock, execute_mock,
            write_to_file_mock, create_root_fs_mock, umount_mock):

        files_info = {
            'path/to/kernel': 'vmlinuz',
            'path/to/ramdisk': 'initrd',
            'sourceabspath/to/efiboot.img': 'path/to/efiboot.img',
            'path/to/grub': 'relpath/to/grub.cfg'
        }

        grubcfg = "grubcfg"
        grub_file = 'tmpdir/relpath/to/grub.cfg'
        gen_cfg_mock.side_effect = (grubcfg,)

        params = ['a=b', 'c']
        grub_options = {'linux': '/vmlinuz',
                        'initrd': '/initrd'}

        uefi_path_info = {
            'sourceabspath/to/efiboot.img': 'path/to/efiboot.img',
            'path/to/grub': 'relpath/to/grub.cfg'}
        grub_rel_path = 'relpath/to/grub.cfg'
        e_img_rel_path = 'path/to/efiboot.img'
        mock_file_handle = mock.MagicMock(spec=io.BytesIO)
        mock_file_handle.__enter__.return_value = 'tmpdir'
        mock_file_handle1 = mock.MagicMock(spec=io.BytesIO)
        mock_file_handle1.__enter__.return_value = 'mountdir'
        tempdir_mock.side_effect = mock_file_handle, mock_file_handle1
        mount_mock.return_value = (uefi_path_info,
                                   e_img_rel_path, grub_rel_path)

        images.create_esp_image_for_uefi('tgt_file',
                                         'path/to/kernel',
                                         'path/to/ramdisk',
                                         deploy_iso='path/to/deploy_iso',
                                         kernel_params=params)
        mount_mock.assert_called_once_with('path/to/deploy_iso', 'mountdir')
        create_root_fs_mock.assert_called_once_with('tmpdir', files_info)
        gen_cfg_mock.assert_any_call(params, CONF.grub_config_template,
                                     grub_options)
        write_to_file_mock.assert_any_call(grub_file, grubcfg)
        execute_mock.assert_called_once_with(
            'mkisofs', '-r', '-V', 'VMEDIA_BOOT_ISO', '-l', '-e',
            'path/to/efiboot.img', '-no-emul-boot', '-o', 'tgt_file', 'tmpdir')
        umount_mock.assert_called_once_with('mountdir')

    @mock.patch.object(utils, 'write_to_file', autospec=True)
    @mock.patch.object(images, '_create_root_fs', autospec=True)
    @mock.patch.object(utils, 'execute', autospec=True)
    @mock.patch.object(utils, 'tempdir', autospec=True)
    @mock.patch.object(images, '_generate_cfg', autospec=True)
    def test_create_esp_image_for_uefi_with_esp_image(
            self, gen_cfg_mock, tempdir_mock, execute_mock,
            create_root_fs_mock, write_to_file_mock):

        files_info = {
            'path/to/kernel': 'vmlinuz',
            'path/to/ramdisk': 'initrd',
            'sourceabspath/to/efiboot.img': 'boot/grub/efiboot.img',
            '/dev/null': 'EFI/MYBOOT/grub.cfg',
        }

        grub_cfg_file = '/EFI/MYBOOT/grub.cfg'
        CONF.set_override('grub_config_path', grub_cfg_file)
        grubcfg = "grubcfg"
        gen_cfg_mock.side_effect = (grubcfg,)

        params = ['a=b', 'c']
        grub_options = {'linux': '/vmlinuz',
                        'initrd': '/initrd'}

        mock_file_handle = mock.MagicMock(spec=io.BytesIO)
        mock_file_handle.__enter__.return_value = 'tmpdir'
        mock_file_handle1 = mock.MagicMock(spec=io.BytesIO)
        mock_file_handle1.__enter__.return_value = 'mountdir'
        tempdir_mock.side_effect = mock_file_handle, mock_file_handle1
        mountdir_grub_cfg_path = 'tmpdir' + grub_cfg_file

        images.create_esp_image_for_uefi(
            'tgt_file', 'path/to/kernel', 'path/to/ramdisk',
            esp_image='sourceabspath/to/efiboot.img',
            kernel_params=params)
        create_root_fs_mock.assert_called_once_with('tmpdir', files_info)
        gen_cfg_mock.assert_any_call(params, CONF.grub_config_template,
                                     grub_options)
        write_to_file_mock.assert_any_call(mountdir_grub_cfg_path, grubcfg)
        execute_mock.assert_called_once_with(
            'mkisofs', '-r', '-V', 'VMEDIA_BOOT_ISO', '-l', '-e',
            'boot/grub/efiboot.img', '-no-emul-boot', '-o', 'tgt_file',
            'tmpdir')

    @mock.patch.object(images, '_create_root_fs', autospec=True)
    @mock.patch.object(utils, 'write_to_file', autospec=True)
    @mock.patch.object(utils, 'tempdir', autospec=True)
    @mock.patch.object(utils, 'execute', autospec=True)
    @mock.patch.object(images, '_generate_cfg', autospec=True)
    def _test_create_isolinux_image_for_bios(
            self, gen_cfg_mock, execute_mock, tempdir_mock,
            write_to_file_mock, create_root_fs_mock, ldlinux_path=None,
            inject_files=None):

        mock_file_handle = mock.MagicMock(spec=io.BytesIO)
        mock_file_handle.__enter__.return_value = 'tmpdir'
        tempdir_mock.return_value = mock_file_handle

        cfg = "cfg"
        cfg_file = 'tmpdir/isolinux/isolinux.cfg'
        gen_cfg_mock.return_value = cfg

        params = ['a=b', 'c']
        isolinux_options = {'kernel': '/vmlinuz',
                            'ramdisk': '/initrd'}

        images.create_isolinux_image_for_bios('tgt_file',
                                              'path/to/kernel',
                                              'path/to/ramdisk',
                                              kernel_params=params,
                                              inject_files=inject_files)

        files_info = {
            'path/to/kernel': 'vmlinuz',
            'path/to/ramdisk': 'initrd',
            CONF.isolinux_bin: 'isolinux/isolinux.bin'
        }
        if inject_files:
            files_info.update(inject_files)
        if ldlinux_path:
            files_info[ldlinux_path] = 'isolinux/ldlinux.c32'
        create_root_fs_mock.assert_called_once_with('tmpdir', files_info)
        gen_cfg_mock.assert_called_once_with(params,
                                             CONF.isolinux_config_template,
                                             isolinux_options)
        write_to_file_mock.assert_called_once_with(cfg_file, cfg)
        execute_mock.assert_called_once_with(
            'mkisofs', '-r', '-V',
            "VMEDIA_BOOT_ISO", '-J', '-l',
            '-no-emul-boot', '-boot-load-size',
            '4', '-boot-info-table', '-b', 'isolinux/isolinux.bin',
            '-o', 'tgt_file', 'tmpdir')

    @mock.patch.object(os.path, 'isfile', autospec=True)
    def test_create_isolinux_image_for_bios(self, mock_isfile):
        mock_isfile.return_value = False
        self._test_create_isolinux_image_for_bios()

    def test_create_isolinux_image_for_bios_conf_ldlinux(self):
        CONF.set_override('ldlinux_c32', 'path/to/ldlinux.c32')
        self._test_create_isolinux_image_for_bios(
            ldlinux_path='path/to/ldlinux.c32')

    @mock.patch.object(os.path, 'isfile', autospec=True)
    def test_create_isolinux_image_for_bios_default_ldlinux(self, mock_isfile):
        mock_isfile.side_effect = [False, True]
        self._test_create_isolinux_image_for_bios(
            ldlinux_path='/usr/share/syslinux/ldlinux.c32')

    @mock.patch.object(os.path, 'isfile', autospec=True)
    def test_create_isolinux_image_for_bios_inject_files(self, mock_isfile):
        mock_isfile.return_value = False
        self._test_create_isolinux_image_for_bios(
            inject_files={'/source': 'target'})

    @mock.patch.object(images, '_umount_without_raise', autospec=True)
    @mock.patch.object(images, '_create_root_fs', autospec=True)
    @mock.patch.object(utils, 'tempdir', autospec=True)
    @mock.patch.object(utils, 'execute', autospec=True)
    @mock.patch.object(os, 'walk', autospec=True)
    def test_create_esp_image_uefi_rootfs_fails(
            self, walk_mock, utils_mock, tempdir_mock,
            create_root_fs_mock, umount_mock):

        mock_file_handle = mock.MagicMock(spec=io.BytesIO)
        mock_file_handle.__enter__.return_value = 'tmpdir'
        mock_file_handle1 = mock.MagicMock(spec=io.BytesIO)
        mock_file_handle1.__enter__.return_value = 'mountdir'
        tempdir_mock.side_effect = mock_file_handle, mock_file_handle1
        create_root_fs_mock.side_effect = IOError

        self.assertRaises(exception.ImageCreationFailed,
                          images.create_esp_image_for_uefi,
                          'tgt_file',
                          'path/to/kernel',
                          'path/to/ramdisk',
                          deploy_iso='path/to/deployiso')
        umount_mock.assert_called_once_with('mountdir')

    @mock.patch.object(images, '_create_root_fs', autospec=True)
    @mock.patch.object(utils, 'tempdir', autospec=True)
    @mock.patch.object(utils, 'execute', autospec=True)
    @mock.patch.object(os, 'walk', autospec=True)
    def test_create_isolinux_image_bios_rootfs_fails(self, walk_mock,
                                                     utils_mock,
                                                     tempdir_mock,
                                                     create_root_fs_mock):
        create_root_fs_mock.side_effect = IOError

        self.assertRaises(exception.ImageCreationFailed,
                          images.create_isolinux_image_for_bios,
                          'tgt_file', 'path/to/kernel',
                          'path/to/ramdisk')

    @mock.patch.object(images, '_umount_without_raise', autospec=True)
    @mock.patch.object(images, '_create_root_fs', autospec=True)
    @mock.patch.object(utils, 'write_to_file', autospec=True)
    @mock.patch.object(utils, 'tempdir', autospec=True)
    @mock.patch.object(utils, 'execute', autospec=True)
    @mock.patch.object(images, '_mount_deploy_iso', autospec=True)
    @mock.patch.object(images, '_generate_cfg', autospec=True)
    def test_create_esp_image_mkisofs_fails(
            self, gen_cfg_mock, mount_mock, utils_mock, tempdir_mock,
            write_to_file_mock, create_root_fs_mock, umount_mock):
        mock_file_handle = mock.MagicMock(spec=io.BytesIO)
        mock_file_handle.__enter__.return_value = 'tmpdir'
        mock_file_handle1 = mock.MagicMock(spec=io.BytesIO)
        mock_file_handle1.__enter__.return_value = 'mountdir'
        tempdir_mock.side_effect = mock_file_handle, mock_file_handle1
        mount_mock.return_value = ({'a': 'a'}, 'b', 'c')
        utils_mock.side_effect = processutils.ProcessExecutionError

        self.assertRaises(exception.ImageCreationFailed,
                          images.create_esp_image_for_uefi,
                          'tgt_file',
                          'path/to/kernel',
                          'path/to/ramdisk',
                          deploy_iso='path/to/deployiso')
        umount_mock.assert_called_once_with('mountdir')

    @mock.patch.object(images, '_create_root_fs', autospec=True)
    @mock.patch.object(utils, 'write_to_file', autospec=True)
    @mock.patch.object(utils, 'tempdir', autospec=True)
    @mock.patch.object(utils, 'execute', autospec=True)
    @mock.patch.object(images, '_generate_cfg', autospec=True)
    def test_create_isolinux_image_bios_mkisofs_fails(self,
                                                      gen_cfg_mock,
                                                      utils_mock,
                                                      tempdir_mock,
                                                      write_to_file_mock,
                                                      create_root_fs_mock):
        mock_file_handle = mock.MagicMock(spec=io.BytesIO)
        mock_file_handle.__enter__.return_value = 'tmpdir'
        tempdir_mock.return_value = mock_file_handle
        utils_mock.side_effect = processutils.ProcessExecutionError

        self.assertRaises(exception.ImageCreationFailed,
                          images.create_isolinux_image_for_bios,
                          'tgt_file', 'path/to/kernel',
                          'path/to/ramdisk')

    @mock.patch.object(images, 'create_esp_image_for_uefi', autospec=True)
    @mock.patch.object(images, 'fetch', autospec=True)
    @mock.patch.object(utils, 'tempdir', autospec=True)
    def test_create_boot_iso_for_uefi_deploy_iso(
            self, tempdir_mock, fetch_images_mock, create_isolinux_mock):
        mock_file_handle = mock.MagicMock(spec=io.BytesIO)
        mock_file_handle.__enter__.return_value = 'tmpdir'
        tempdir_mock.return_value = mock_file_handle

        images.create_boot_iso(
            'ctx', 'output_file', 'kernel-uuid',
            'ramdisk-uuid', deploy_iso_href='deploy_iso-uuid',
            root_uuid='root-uuid', kernel_params='kernel-params',
            boot_mode='uefi')

        fetch_images_mock.assert_any_call(
            'ctx', 'kernel-uuid', 'tmpdir/kernel-uuid')
        fetch_images_mock.assert_any_call(
            'ctx', 'ramdisk-uuid', 'tmpdir/ramdisk-uuid')
        fetch_images_mock.assert_any_call(
            'ctx', 'deploy_iso-uuid', 'tmpdir/deploy_iso-uuid')

        params = ['root=UUID=root-uuid', 'kernel-params']
        create_isolinux_mock.assert_called_once_with(
            'output_file', 'tmpdir/kernel-uuid', 'tmpdir/ramdisk-uuid',
            deploy_iso='tmpdir/deploy_iso-uuid',
            esp_image=None, kernel_params=params, inject_files=None)

    @mock.patch.object(images, 'create_esp_image_for_uefi', autospec=True)
    @mock.patch.object(images, 'fetch', autospec=True)
    @mock.patch.object(utils, 'tempdir', autospec=True)
    def test_create_boot_iso_for_uefi_esp_image(
            self, tempdir_mock, fetch_images_mock, create_isolinux_mock):
        mock_file_handle = mock.MagicMock(spec=io.BytesIO)
        mock_file_handle.__enter__.return_value = 'tmpdir'
        tempdir_mock.return_value = mock_file_handle

        images.create_boot_iso(
            'ctx', 'output_file', 'kernel-uuid',
            'ramdisk-uuid', esp_image_href='efiboot-uuid',
            root_uuid='root-uuid', kernel_params='kernel-params',
            boot_mode='uefi')

        fetch_images_mock.assert_any_call(
            'ctx', 'kernel-uuid', 'tmpdir/kernel-uuid')
        fetch_images_mock.assert_any_call(
            'ctx', 'ramdisk-uuid', 'tmpdir/ramdisk-uuid')
        fetch_images_mock.assert_any_call(
            'ctx', 'efiboot-uuid', 'tmpdir/efiboot-uuid')

        params = ['root=UUID=root-uuid', 'kernel-params']
        create_isolinux_mock.assert_called_once_with(
            'output_file', 'tmpdir/kernel-uuid', 'tmpdir/ramdisk-uuid',
            deploy_iso=None, esp_image='tmpdir/efiboot-uuid',
            kernel_params=params, inject_files=None)

    @mock.patch.object(images, 'create_esp_image_for_uefi', autospec=True)
    @mock.patch.object(images, 'fetch', autospec=True)
    @mock.patch.object(utils, 'tempdir', autospec=True)
    def test_create_boot_iso_for_uefi_deploy_iso_for_hrefs(
            self, tempdir_mock, fetch_images_mock, create_isolinux_mock):
        mock_file_handle = mock.MagicMock(spec=io.BytesIO)
        mock_file_handle.__enter__.return_value = 'tmpdir'
        tempdir_mock.return_value = mock_file_handle

        images.create_boot_iso(
            'ctx', 'output_file', 'http://kernel-href', 'http://ramdisk-href',
            deploy_iso_href='http://deploy_iso-href',
            root_uuid='root-uuid', kernel_params='kernel-params',
            boot_mode='uefi')

        expected_calls = [mock.call('ctx', 'http://kernel-href',
                                    'tmpdir/kernel-href'),
                          mock.call('ctx', 'http://ramdisk-href',
                                    'tmpdir/ramdisk-href'),
                          mock.call('ctx', 'http://deploy_iso-href',
                                    'tmpdir/deploy_iso-href')]
        fetch_images_mock.assert_has_calls(expected_calls)
        params = ['root=UUID=root-uuid', 'kernel-params']
        create_isolinux_mock.assert_called_once_with(
            'output_file', 'tmpdir/kernel-href', 'tmpdir/ramdisk-href',
            deploy_iso='tmpdir/deploy_iso-href',
            esp_image=None, kernel_params=params, inject_files=None)

    @mock.patch.object(images, 'create_esp_image_for_uefi', autospec=True)
    @mock.patch.object(images, 'fetch', autospec=True)
    @mock.patch.object(utils, 'tempdir', autospec=True)
    def test_create_boot_iso_for_uefi_esp_image_for_hrefs(
            self, tempdir_mock, fetch_images_mock, create_isolinux_mock):
        mock_file_handle = mock.MagicMock(spec=io.BytesIO)
        mock_file_handle.__enter__.return_value = 'tmpdir'
        tempdir_mock.return_value = mock_file_handle

        images.create_boot_iso(
            'ctx', 'output_file', 'http://kernel-href', 'http://ramdisk-href',
            esp_image_href='http://efiboot-href',
            root_uuid='root-uuid', kernel_params='kernel-params',
            boot_mode='uefi')

        expected_calls = [mock.call('ctx', 'http://kernel-href',
                                    'tmpdir/kernel-href'),
                          mock.call('ctx', 'http://ramdisk-href',
                                    'tmpdir/ramdisk-href'),
                          mock.call('ctx', 'http://efiboot-href',
                                    'tmpdir/efiboot-href')]
        fetch_images_mock.assert_has_calls(expected_calls)
        params = ['root=UUID=root-uuid', 'kernel-params']
        create_isolinux_mock.assert_called_once_with(
            'output_file', 'tmpdir/kernel-href', 'tmpdir/ramdisk-href',
            deploy_iso=None, esp_image='tmpdir/efiboot-href',
            kernel_params=params, inject_files=None)

    @mock.patch.object(images, 'create_isolinux_image_for_bios', autospec=True)
    @mock.patch.object(images, 'fetch', autospec=True)
    @mock.patch.object(utils, 'tempdir', autospec=True)
    def test_create_boot_iso_for_bios(
            self, tempdir_mock, fetch_images_mock, create_isolinux_mock):
        mock_file_handle = mock.MagicMock(spec=io.BytesIO)
        mock_file_handle.__enter__.return_value = 'tmpdir'
        tempdir_mock.return_value = mock_file_handle

        images.create_boot_iso('ctx', 'output_file', 'kernel-uuid',
                               'ramdisk-uuid', 'deploy_iso-uuid',
                               'efiboot-uuid', 'root-uuid',
                               'kernel-params', 'bios')

        fetch_images_mock.assert_any_call(
            'ctx', 'kernel-uuid', 'tmpdir/kernel-uuid')
        fetch_images_mock.assert_any_call(
            'ctx', 'ramdisk-uuid', 'tmpdir/ramdisk-uuid')

        # Note (NobodyCam): the original assert asserted that fetch_images
        #                   was not called with parameters, this did not
        #                   work, So I instead assert that there were only
        #                   Two calls to the mock validating the above
        #                   asserts.
        self.assertEqual(2, fetch_images_mock.call_count)

        params = ['root=UUID=root-uuid', 'kernel-params']
        create_isolinux_mock.assert_called_once_with(
            'output_file', 'tmpdir/kernel-uuid', 'tmpdir/ramdisk-uuid',
            kernel_params=params, inject_files=None)

    @mock.patch.object(images, 'create_isolinux_image_for_bios', autospec=True)
    @mock.patch.object(images, 'fetch', autospec=True)
    @mock.patch.object(utils, 'tempdir', autospec=True)
    def test_create_boot_iso_for_bios_with_no_boot_mode(self, tempdir_mock,
                                                        fetch_images_mock,
                                                        create_isolinux_mock):
        mock_file_handle = mock.MagicMock(spec=io.BytesIO)
        mock_file_handle.__enter__.return_value = 'tmpdir'
        tempdir_mock.return_value = mock_file_handle

        images.create_boot_iso('ctx', 'output_file', 'kernel-uuid',
                               'ramdisk-uuid', 'deploy_iso-uuid',
                               'efiboot-uuid', 'root-uuid',
                               'kernel-params', None)

        fetch_images_mock.assert_any_call(
            'ctx', 'kernel-uuid', 'tmpdir/kernel-uuid')
        fetch_images_mock.assert_any_call(
            'ctx', 'ramdisk-uuid', 'tmpdir/ramdisk-uuid')

        params = ['root=UUID=root-uuid', 'kernel-params']
        create_isolinux_mock.assert_called_once_with(
            'output_file', 'tmpdir/kernel-uuid', 'tmpdir/ramdisk-uuid',
            kernel_params=params, inject_files=None)

    @mock.patch.object(image_service, 'get_image_service', autospec=True)
    def test_get_glance_image_properties_no_such_prop(self,
                                                      image_service_mock):

        prop_dict = {'properties': {'p1': 'v1',
                                    'p2': 'v2'}}

        image_service_obj_mock = image_service_mock.return_value
        image_service_obj_mock.show.return_value = prop_dict

        ret_val = images.get_image_properties('con', 'uuid',
                                              ['p1', 'p2', 'p3'])
        image_service_mock.assert_called_once_with('uuid', context='con')
        image_service_obj_mock.show.assert_called_once_with('uuid')
        self.assertEqual({'p1': 'v1',
                          'p2': 'v2',
                          'p3': None}, ret_val)

    @mock.patch.object(image_service, 'get_image_service', autospec=True)
    def test_get_glance_image_properties_default_all(
            self, image_service_mock):

        prop_dict = {'properties': {'p1': 'v1',
                                    'p2': 'v2'}}

        image_service_obj_mock = image_service_mock.return_value
        image_service_obj_mock.show.return_value = prop_dict

        ret_val = images.get_image_properties('con', 'uuid')
        image_service_mock.assert_called_once_with('uuid', context='con')
        image_service_obj_mock.show.assert_called_once_with('uuid')
        self.assertEqual({'p1': 'v1',
                          'p2': 'v2'}, ret_val)

    @mock.patch.object(image_service, 'get_image_service', autospec=True)
    def test_get_glance_image_properties_with_prop_subset(
            self, image_service_mock):

        prop_dict = {'properties': {'p1': 'v1',
                                    'p2': 'v2',
                                    'p3': 'v3'}}

        image_service_obj_mock = image_service_mock.return_value
        image_service_obj_mock.show.return_value = prop_dict

        ret_val = images.get_image_properties('con', 'uuid',
                                              ['p1', 'p3'])
        image_service_mock.assert_called_once_with('uuid', context='con')
        image_service_obj_mock.show.assert_called_once_with('uuid')
        self.assertEqual({'p1': 'v1',
                          'p3': 'v3'}, ret_val)

    @mock.patch.object(image_service, 'GlanceImageService', autospec=True)
    def test_get_temp_url_for_glance_image(self, image_service_mock):

        direct_url = 'swift+http://host/v1/AUTH_xx/con/obj'
        image_info = {'id': 'qwe', 'properties': {'direct_url': direct_url}}
        glance_service_mock = image_service_mock.return_value
        glance_service_mock.swift_temp_url.return_value = 'temp-url'
        glance_service_mock.show.return_value = image_info

        temp_url = images.get_temp_url_for_glance_image('context',
                                                        'glance_uuid')

        glance_service_mock.show.assert_called_once_with('glance_uuid')
        self.assertEqual('temp-url', temp_url)
